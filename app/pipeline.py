from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import random
from time import perf_counter

from app.cache_lookup import CacheLookupService
from app.clients.event_client import EventBusClient
from app.clients.llm_client import DecisionProvider
from app.clients.policy_client import OPAClient
from app.clients.ticket_client import TicketStoreClient
from app.clients.vector_client import VectorStoreClient
from app.embedding import EmbeddingService
from app.kpi import KPITracker
from app.mode_manager import ModeManager
from app.models import (
    AccessRequest,
    AccessResponse,
    AccessScores,
    AuditEvent,
    CacheUpdateMessage,
    Decision,
    DecisionSource,
    FeedbackEvent,
    LLMRationale,
    LLMUsage,
    Sensitivity,
)
from app.threat_screen import ThreatScreenService
from app.ttl import compute_dynamic_ttl
from app.validation import ValidationService


@dataclass
class AccessPipeline:
    policy_version: str
    mode_manager: ModeManager
    ingestion: object
    policy: OPAClient
    embedding: EmbeddingService
    threat_screen: ThreatScreenService
    cache_lookup: CacheLookupService
    validation: ValidationService
    llm_provider: DecisionProvider
    shadow_llm_provider: DecisionProvider | None
    shadow_sampling_rate: float
    ticket_store: TicketStoreClient
    events: EventBusClient
    vector_store: VectorStoreClient
    kpi_tracker: KPITracker
    # Ablation control: "none" | "no_cache_reeval" | "no_cache" | "llm_only"
    ablation_mode: str = "none"

    def decide(self, req: AccessRequest) -> AccessResponse:
        start = perf_counter()
        req = self.ingestion.normalize(req)
        mode = self.mode_manager.get_mode()
        thresholds = self.mode_manager.thresholds()

        # Ablation: llm_only skips hard policy evaluation entirely
        if self.ablation_mode != "llm_only":
            hard = self.policy.evaluate_hard(req)
            if not hard.allow:
                return self._finalize(
                    req=req,
                    decision=Decision.DENY,
                    source=DecisionSource.hard_rule,
                    reason_code=hard.reason_code,
                    confidence=1.0,
                    scores=AccessScores(),
                    mode=mode.value,
                    start=start,
                )

        embedding = self.embedding.encode(req.query.prompt)
        threat = self.threat_screen.evaluate(embedding)
        if threat.similarity >= thresholds.t_attack:
            return self._finalize(
                req=req,
                decision=Decision.DENY,
                source=DecisionSource.threat_gate,
                reason_code="THREAT_PATTERN_MATCH",
                confidence=min(1.0, max(threat.similarity, 0.85)),
                scores=AccessScores(threat_similarity=threat.similarity),
                mode=mode.value,
                start=start,
                suspicious=True,
            )

        # Ablation: no_cache and llm_only skip cache lookup entirely
        if self.ablation_mode not in ("no_cache", "llm_only"):
            candidate = self.cache_lookup.lookup(req=req, embedding=embedding, policy_version=self.policy_version)
            if candidate.hit and candidate.similarity >= thresholds.t_hit:
                return self._handle_cache_hit(req, embedding, candidate.similarity, mode.value, start, DecisionSource.cache)

            if candidate.hit and thresholds.t_validate_low <= candidate.similarity < thresholds.t_hit:
                validation = self.validation.validate(req.query.prompt, candidate.cached_text or "")
                if validation.is_hit:
                    return self._handle_cache_hit(
                        req,
                        embedding,
                        candidate.similarity,
                        mode.value,
                        start,
                        DecisionSource.validation,
                        cross_score=validation.score,
                    )
                return self._llm_path(
                    req,
                    embedding,
                    candidate.similarity,
                    mode.value,
                    start,
                    cross_score=validation.score,
                )
            return self._llm_path(req, embedding, candidate.similarity if candidate.hit else None, mode.value, start)

        return self._llm_path(req, embedding, None, mode.value, start)

    def _handle_cache_hit(
        self,
        req: AccessRequest,
        embedding: list[float],
        cache_similarity: float,
        mode: str,
        start: float,
        source: DecisionSource,
        cross_score: float | None = None,
    ) -> AccessResponse:
        scores = AccessScores(cache_similarity=cache_similarity, cross_encoder_score=cross_score)
        # Ablation: no_cache_reeval skips soft policy re-evaluation and always serves ALLOW_CACHE.
        if self.ablation_mode == "no_cache_reeval":
            return self._finalize(
                req=req,
                decision=Decision.ALLOW_CACHE,
                source=source,
                reason_code="CACHE_HIT_NO_REEVAL",
                confidence=min(1.0, cache_similarity),
                scores=scores,
                mode=mode,
                start=start,
                embedding=embedding,
            )
        soft = self.policy.evaluate_soft(req)
        if soft.allow:
            return self._finalize(
                req=req,
                decision=Decision.ALLOW_CACHE,
                source=source,
                reason_code="CACHE_HIT_SOFT_PASS",
                confidence=min(1.0, cache_similarity),
                scores=scores,
                mode=mode,
                start=start,
                embedding=embedding,
            )
        if self.ticket_store.has_ticket(req.user.user_id, req.resource.resource_id):
            return self._finalize(
                req=req,
                decision=Decision.ALLOW_EMERGENCY,
                source=source,
                reason_code="EMERGENCY_TICKET_VALID",
                confidence=0.75,
                scores=scores,
                mode=mode,
                start=start,
                embedding=embedding,
            )
        return self._llm_path(req, embedding, cache_similarity, mode, start, cross_score)

    def _llm_path(
        self,
        req: AccessRequest,
        embedding: list[float],
        cache_similarity: float | None,
        mode: str,
        start: float,
        cross_score: float | None = None,
    ) -> AccessResponse:
        scores = AccessScores(cache_similarity=cache_similarity, cross_encoder_score=cross_score)
        soft = self.policy.evaluate_soft(req)
        if not soft.allow:
            # Pre-authorized emergency ticket always bypasses soft rules.
            if self.ticket_store.has_ticket(req.user.user_id, req.resource.resource_id):
                return self._finalize(
                    req=req,
                    decision=Decision.ALLOW_EMERGENCY,
                    source=DecisionSource.hard_rule,
                    reason_code="EMERGENCY_TICKET_VALID",
                    confidence=0.75,
                    scores=scores,
                    mode=mode,
                    start=start,
                    embedding=embedding,
                )
            # Time-window restriction is deterministic — skip LLM, no emergency override.
            if soft.reason_code == "OUT_OF_HOURS_FAST_PATH_REVIEW":
                return self._finalize(
                    req=req,
                    decision=Decision.ESCALATE_HUMAN,
                    source=DecisionSource.hard_rule,
                    reason_code=soft.reason_code,
                    confidence=0.9,
                    scores=scores,
                    mode=mode,
                    start=start,
                )
            # For incident-state restrictions (critical, elevated+confidential), fall through
            # to LLM so it can weigh context and potentially grant ALLOW_EMERGENCY.

        proposal = self.llm_provider.evaluate(
            {
                "request_id": req.request_id,
                "user": req.user.model_dump(),
                "resource": req.resource.model_dump(),
                "context": req.context.model_dump(),
                "query": req.query.model_dump(),
            }
        )

        # Fail-closed for sensitive data when provider fails or confidence is too low.
        if proposal.reason_code in {"OPENAI_UNCONFIGURED", "OPENAI_EVAL_FAILED", "OPENAI_SDK_MISSING", "VLLM_EVAL_FAILED"}:
            if req.resource.sensitivity in {Sensitivity.restricted, Sensitivity.confidential}:
                return self._finalize(
                    req=req,
                    decision=Decision.DENY,
                    source=DecisionSource.llm,
                    reason_code="FAIL_CLOSED_LLM_UNAVAILABLE",
                    confidence=1.0,
                    scores=AccessScores(cache_similarity=cache_similarity, cross_encoder_score=cross_score),
                    mode=mode,
                    start=start,
                    rationale=proposal.rationale,
                )

        decision, veto_reason = self.policy.veto(req, proposal.proposed_decision)
        reason = proposal.reason_code if veto_reason == "VETO_PASS" else veto_reason
        # Per dataflow: issue emergency bypass tickets only when the model explicitly proposes ALLOW_EMERGENCY.
        if proposal.proposed_decision == Decision.ALLOW_EMERGENCY and decision in {Decision.ALLOW, Decision.ALLOW_EMERGENCY}:
            self.ticket_store.issue_ticket(req.user.user_id, req.resource.resource_id, ttl_seconds=900)

        if self.shadow_llm_provider and random.random() <= max(0.0, min(1.0, self.shadow_sampling_rate)):
            shadow = self.shadow_llm_provider.evaluate(
                {
                    "request_id": req.request_id,
                    "user": req.user.model_dump(),
                    "resource": req.resource.model_dump(),
                    "context": req.context.model_dump(),
                    "query": req.query.model_dump(),
                }
            )
            self.events.publish(
                "llm.shadow",
                {
                    "request_id": req.request_id,
                    "primary_decision": decision.value,
                    "primary_reason": reason,
                    "shadow_decision": shadow.proposed_decision.value,
                    "shadow_reason": shadow.reason_code,
                    "shadow_confidence": shadow.confidence,
                },
            )

        return self._finalize(
            req=req,
            decision=decision,
            source=DecisionSource.llm,
            reason_code=reason,
            confidence=proposal.confidence,
            scores=AccessScores(cache_similarity=cache_similarity, cross_encoder_score=cross_score),
            mode=mode,
            start=start,
            embedding=embedding,
            llm_usage=proposal.llm_usage,
            estimated_cost_usd=proposal.estimated_cost_usd,
            rationale=proposal.rationale,
        )

    def _finalize(
        self,
        req: AccessRequest,
        decision: Decision,
        source: DecisionSource,
        reason_code: str,
        confidence: float,
        scores: AccessScores,
        mode: str,
        start: float,
        embedding: list[float] | None = None,
        suspicious: bool = False,
        llm_usage: LLMUsage | None = None,
        estimated_cost_usd: float = 0.0,
        rationale: LLMRationale | None = None,
    ) -> AccessResponse:
        latency_ms = int((perf_counter() - start) * 1000)
        resp = AccessResponse(
            request_id=req.request_id,
            decision=decision,
            decision_source=source,
            confidence=max(0.0, min(1.0, confidence)),
            reason_code=reason_code,
            scores=scores,
            policy_version=self.policy_version,
            mode=mode,
            latency_ms=latency_ms,
            llm_usage=llm_usage,
            estimated_cost_usd=estimated_cost_usd,
            rationale=rationale,
        )
        self._emit_events(req, resp, embedding or [], suspicious)
        return resp

    def _emit_events(self, req: AccessRequest, resp: AccessResponse, embedding: list[float], suspicious: bool) -> None:
        audit = AuditEvent(
            request_id=req.request_id,
            user_id=req.user.user_id,
            resource_id=req.resource.resource_id,
            decision=resp.decision,
            decision_source=resp.decision_source,
            policy_version=resp.policy_version,
            mode=resp.mode,
            latency_ms=resp.latency_ms,
            scores=resp.scores,
        )
        self.events.publish("audit.events", audit.model_dump(mode="json"))
        if embedding and resp.decision != Decision.ESCALATE_HUMAN:
            update = CacheUpdateMessage(request=req, response=resp, embedding=embedding)
            self.events.publish("cache.update", update.model_dump(mode="json"))
            if not self.events.enabled:
                self._write_cache_update_sync(update)
        feedback = FeedbackEvent(
            request_id=req.request_id,
            prompt=req.query.prompt,
            decision=resp.decision,
            reason_code=resp.reason_code,
            suspicious=suspicious,
        )
        self.events.publish("feedback.events", feedback.model_dump(mode="json"))
        self.kpi_tracker.record(resp)

    def _write_cache_update_sync(self, update: CacheUpdateMessage) -> None:
        ttl = compute_dynamic_ttl(update.request, update.response.confidence, policy_stability_factor=1.0)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        item_id = f"{update.request.user.user_id}:{update.request.resource.resource_id}:{update.request.request_id}"
        self.vector_store.upsert_cache_entry(
            item_id=item_id,
            embedding=update.embedding,
            payload={
                "role": update.request.user.role,
                "department": update.request.user.department,
                "region": update.request.user.region,
                "clearance_level": update.request.user.clearance_level,
                "resource_type": update.request.resource.resource_type,
                "policy_version": update.response.policy_version,
                "cached_text": update.request.query.prompt,
                "cached_decision": update.response.decision,
                "ttl_seconds": ttl,
                "expires_at_ts": int(expires_at.timestamp()),
                "expires_at_utc": expires_at.isoformat(),
            },
        )
