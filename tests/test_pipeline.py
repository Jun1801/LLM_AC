from __future__ import annotations

from datetime import datetime, timezone

from app.cache_lookup import CacheLookupService
from app.clients.event_client import EventBusClient
from app.clients.llm_client import DecisionProvider
from app.clients.policy_client import OPAClient
from app.clients.ticket_client import TicketStoreClient
from app.clients.vector_client import VectorStoreClient
from app.embedding import EmbeddingService
from app.ingestion import IngestionService
from app.kpi import KPITracker
from app.mode_manager import ModeManager
from app.models import (
    CacheCandidate,
    Decision,
    IncidentState,
    LLMDecisionProposal,
    PolicyResult,
    Sensitivity,
    ThreatResult,
    ValidationResult,
)
from app.pipeline import AccessPipeline


class DummyProvider(DecisionProvider):
    def __init__(self, proposal: LLMDecisionProposal):
        self.proposal = proposal

    def evaluate(self, structured_facts):
        return self.proposal

    def ping(self):
        return True, "ok"


class DummyPolicy(OPAClient):
    def __init__(self):
        super().__init__(base_url="", enabled=False)
        self.hard = PolicyResult(allow=True, reason_code="HARD_POLICY_PASS")
        self.soft = PolicyResult(allow=True, reason_code="SOFT_POLICY_PASS")

    def evaluate_hard(self, req):
        return self.hard

    def evaluate_soft(self, req):
        return self.soft


class DummyThreat:
    def __init__(self, sim: float):
        self.sim = sim

    def evaluate(self, embedding):
        return ThreatResult(similarity=self.sim)


class DummyCache:
    def __init__(self, candidate: CacheCandidate):
        self.candidate = candidate

    def lookup(self, req, embedding, policy_version):
        return self.candidate


class DummyValidation:
    def __init__(self, is_hit: bool, score: float):
        self.result = ValidationResult(is_hit=is_hit, score=score)

    def validate(self, query_text, cached_text):
        return self.result


def make_pipeline(
    threat_sim: float,
    cache_candidate: CacheCandidate,
    validation_hit: bool = True,
    llm_proposal: LLMDecisionProposal | None = None,
):
    policy = DummyPolicy()
    provider = DummyProvider(
        llm_proposal
        or LLMDecisionProposal(
            proposed_decision=Decision.ALLOW,
            confidence=0.9,
            reason_code="LLM_ALLOW",
            estimated_cost_usd=0.0,
        )
    )
    return AccessPipeline(
        policy_version="2026-04-04",
        mode_manager=ModeManager(),
        ingestion=IngestionService(),
        policy=policy,
        embedding=EmbeddingService(
            model_id="test-embedding",
            expected_dim=16,
            _model=type(
                "FakeSentenceTransformer",
                (),
                {
                    "encode_query": staticmethod(lambda text, **kwargs: [0.1] * 16),
                    "get_sentence_embedding_dimension": staticmethod(lambda: 16),
                },
            )(),
        ),
        threat_screen=DummyThreat(threat_sim),
        cache_lookup=DummyCache(cache_candidate),
        validation=DummyValidation(validation_hit, 0.81),
        llm_provider=provider,
        shadow_llm_provider=None,
        shadow_sampling_rate=0.0,
        ticket_store=TicketStoreClient(enabled=False),
        events=EventBusClient(enabled=False),
        vector_store=VectorStoreClient(enabled=False, vector_size=16),
        kpi_tracker=KPITracker(),
    )


def make_fallback_policy_pipeline(
    threat_sim: float,
    cache_candidate: CacheCandidate,
    llm_proposal: LLMDecisionProposal | None = None,
):
    provider = DummyProvider(
        llm_proposal
        or LLMDecisionProposal(
            proposed_decision=Decision.ALLOW,
            confidence=0.9,
            reason_code="LLM_ALLOW",
            estimated_cost_usd=0.0,
        )
    )
    return AccessPipeline(
        policy_version="2026-04-04",
        mode_manager=ModeManager(),
        ingestion=IngestionService(),
        policy=OPAClient(base_url="", enabled=False),
        embedding=EmbeddingService(
            model_id="test-embedding",
            expected_dim=16,
            _model=type(
                "FakeSentenceTransformer",
                (),
                {
                    "encode_query": staticmethod(lambda text, **kwargs: [0.1] * 16),
                    "get_sentence_embedding_dimension": staticmethod(lambda: 16),
                },
            )(),
        ),
        threat_screen=DummyThreat(threat_sim),
        cache_lookup=DummyCache(cache_candidate),
        validation=DummyValidation(True, 0.81),
        llm_provider=provider,
        shadow_llm_provider=None,
        shadow_sampling_rate=0.0,
        ticket_store=TicketStoreClient(enabled=False),
        events=EventBusClient(enabled=False),
        vector_store=VectorStoreClient(enabled=False, vector_size=16),
        kpi_tracker=KPITracker(),
    )


def test_hard_rule_precedence(sample_request):
    pipeline = make_pipeline(threat_sim=0.0, cache_candidate=CacheCandidate(hit=False))
    pipeline.policy.hard = PolicyResult(allow=False, reason_code="BLOCKED_USER")
    resp = pipeline.decide(sample_request)
    assert resp.decision == Decision.DENY
    assert resp.reason_code == "BLOCKED_USER"


def test_threat_threshold_exact_denies(sample_request):
    pipeline = make_pipeline(threat_sim=0.85, cache_candidate=CacheCandidate(hit=False))
    resp = pipeline.decide(sample_request)
    assert resp.decision == Decision.DENY
    assert resp.reason_code == "THREAT_PATTERN_MATCH"


def test_cache_hit_at_090_goes_direct_soft_rule(sample_request):
    pipeline = make_pipeline(
        threat_sim=0.1,
        cache_candidate=CacheCandidate(hit=True, similarity=0.90, cached_text="Need access to report 2026"),
    )
    resp = pipeline.decide(sample_request)
    assert resp.decision == Decision.ALLOW_CACHE
    assert resp.decision_source.value == "cache"


def test_validation_band_at_070_uses_validation_path(sample_request):
    pipeline = make_pipeline(
        threat_sim=0.1,
        cache_candidate=CacheCandidate(hit=True, similarity=0.70, cached_text="Need access to report 2026"),
        validation_hit=True,
    )
    resp = pipeline.decide(sample_request)
    assert resp.decision == Decision.ALLOW_CACHE
    assert resp.decision_source.value == "validation"


def test_clearance_guard_denies_before_semantic_or_llm(sample_request):
    sample_request.resource.sensitivity = Sensitivity.confidential
    sample_request.user.clearance_level = 2
    pipeline = make_fallback_policy_pipeline(
        threat_sim=0.1,
        cache_candidate=CacheCandidate(hit=True, similarity=0.95, cached_text="Need access to report 2026"),
    )
    resp = pipeline.decide(sample_request)
    assert resp.decision == Decision.DENY
    assert resp.decision_source.value == "hard_rule"
    assert resp.reason_code == "CLEARANCE_TOO_LOW"


def test_role_resource_guard_denies_before_semantic_or_llm(sample_request):
    sample_request.resource.resource_type = "dataset"
    pipeline = make_fallback_policy_pipeline(
        threat_sim=0.1,
        cache_candidate=CacheCandidate(hit=True, similarity=0.95, cached_text="Need access to report 2026"),
    )
    resp = pipeline.decide(sample_request)
    assert resp.decision == Decision.DENY
    assert resp.decision_source.value == "hard_rule"
    assert resp.reason_code == "ROLE_RESOURCE_DENIED"


def test_validation_fallback_to_llm_preserves_cross_encoder_score(sample_request):
    pipeline = make_pipeline(
        threat_sim=0.1,
        cache_candidate=CacheCandidate(hit=True, similarity=0.75, cached_text="Need access to report 2026"),
        validation_hit=False,
        llm_proposal=LLMDecisionProposal(
            proposed_decision=Decision.ALLOW,
            confidence=0.9,
            reason_code="LLM_ALLOW",
            estimated_cost_usd=0.00111,
        ),
    )
    resp = pipeline.decide(sample_request)
    assert resp.decision == Decision.ALLOW
    assert resp.decision_source.value == "llm"
    assert resp.scores.cache_similarity == 0.75
    assert resp.scores.cross_encoder_score == 0.81


def test_llm_rationale_is_exposed_in_response(sample_request):
    pipeline = make_pipeline(
        threat_sim=0.1,
        cache_candidate=CacheCandidate(hit=False),
        llm_proposal=LLMDecisionProposal(
            proposed_decision=Decision.ALLOW,
            confidence=0.9,
            reason_code="LLM_ALLOW",
            estimated_cost_usd=0.00111,
            rationale={
                "summary": "The request matches the current access context.",
                "facts": ["role=analyst", "mfa_state=passed"],
            },
        ),
    )
    resp = pipeline.decide(sample_request)
    assert resp.decision == Decision.ALLOW
    assert resp.rationale is not None
    assert resp.rationale.summary == "The request matches the current access context."
    assert resp.rationale.facts == ["role=analyst", "mfa_state=passed"]


def test_elevated_confidential_soft_rule_falls_through_to_llm(sample_request):
    sample_request.context.incident_state = IncidentState.elevated
    sample_request.resource.sensitivity = Sensitivity.confidential
    sample_request.user.clearance_level = 3
    pipeline = make_fallback_policy_pipeline(
        threat_sim=0.1,
        cache_candidate=CacheCandidate(hit=True, similarity=0.95, cached_text="Need access to report 2026"),
        llm_proposal=LLMDecisionProposal(
            proposed_decision=Decision.ESCALATE_HUMAN,
            confidence=0.7,
            reason_code="LLM_REVIEW",
            estimated_cost_usd=0.001,
        ),
    )
    resp = pipeline.decide(sample_request)
    assert resp.decision == Decision.ESCALATE_HUMAN
    assert resp.decision_source.value == "llm"


def test_out_of_hours_soft_rule_falls_through_to_llm(sample_request):
    sample_request.timestamp_utc = datetime(2026, 4, 14, 3, 0, tzinfo=timezone.utc)
    pipeline = make_fallback_policy_pipeline(
        threat_sim=0.1,
        cache_candidate=CacheCandidate(hit=True, similarity=0.95, cached_text="Need access to report 2026"),
        llm_proposal=LLMDecisionProposal(
            proposed_decision=Decision.ESCALATE_HUMAN,
            confidence=0.7,
            reason_code="LLM_REVIEW",
            estimated_cost_usd=0.001,
        ),
    )
    resp = pipeline.decide(sample_request)
    assert resp.decision == Decision.ESCALATE_HUMAN
    assert resp.decision_source.value == "llm"
    assert resp.reason_code == "LLM_REVIEW"


def test_elevated_confidential_soft_rule_allows_emergency_ticket(sample_request):
    sample_request.context.incident_state = IncidentState.elevated
    sample_request.resource.sensitivity = Sensitivity.confidential
    sample_request.user.clearance_level = 3
    pipeline = make_fallback_policy_pipeline(
        threat_sim=0.1,
        cache_candidate=CacheCandidate(hit=True, similarity=0.95, cached_text="Need access to report 2026"),
    )
    pipeline.ticket_store.issue_ticket(sample_request.user.user_id, sample_request.resource.resource_id, ttl_seconds=900)
    resp = pipeline.decide(sample_request)
    assert resp.decision == Decision.ALLOW_EMERGENCY
    assert resp.decision_source.value == "cache"


def test_elevated_internal_soft_rule_keeps_fast_path(sample_request):
    sample_request.context.incident_state = IncidentState.elevated
    sample_request.resource.sensitivity = Sensitivity.internal
    pipeline = make_fallback_policy_pipeline(
        threat_sim=0.1,
        cache_candidate=CacheCandidate(hit=True, similarity=0.95, cached_text="Need access to report 2026"),
    )
    resp = pipeline.decide(sample_request)
    assert resp.decision == Decision.ALLOW_CACHE
    assert resp.decision_source.value == "cache"


def test_cache_below_070_goes_llm(sample_request):
    pipeline = make_pipeline(
        threat_sim=0.1,
        cache_candidate=CacheCandidate(hit=True, similarity=0.6999, cached_text="Need access to report 2026"),
        llm_proposal=LLMDecisionProposal(
            proposed_decision=Decision.ALLOW,
            confidence=0.9,
            reason_code="LLM_ALLOW",
            estimated_cost_usd=0.00111,
        ),
    )
    resp = pipeline.decide(sample_request)
    assert resp.decision == Decision.ALLOW
    assert resp.decision_source.value == "llm"
    assert resp.estimated_cost_usd == 0.00111


def test_fail_closed_when_llm_unavailable_for_sensitive_resource(sample_request):
    sample_request.resource.sensitivity = Sensitivity.confidential
    pipeline = make_pipeline(
        threat_sim=0.1,
        cache_candidate=CacheCandidate(hit=False),
        llm_proposal=LLMDecisionProposal(
            proposed_decision=Decision.ESCALATE_HUMAN,
            confidence=0.3,
            reason_code="OPENAI_EVAL_FAILED",
            estimated_cost_usd=0.0,
        ),
    )
    resp = pipeline.decide(sample_request)
    assert resp.decision == Decision.DENY
    assert resp.reason_code == "FAIL_CLOSED_LLM_UNAVAILABLE"


def test_veto_overrides_unsafe_decision(sample_request):
    pipeline = make_pipeline(
        threat_sim=0.1,
        cache_candidate=CacheCandidate(hit=False),
        llm_proposal=LLMDecisionProposal(
            proposed_decision=Decision.ALLOW,
            confidence=0.9,
            reason_code="LLM_ALLOW",
            estimated_cost_usd=0.00123,
        ),
    )
    pipeline.policy.hard = PolicyResult(allow=False, reason_code="MFA_REQUIRED")
    resp = pipeline.decide(sample_request)
    assert resp.decision == Decision.DENY


def test_ticket_issued_only_for_allow_emergency_proposal(sample_request):
    allow_pipeline = make_pipeline(
        threat_sim=0.1,
        cache_candidate=CacheCandidate(hit=False),
        llm_proposal=LLMDecisionProposal(
            proposed_decision=Decision.ALLOW,
            confidence=0.9,
            reason_code="LLM_ALLOW",
            estimated_cost_usd=0.0,
        ),
    )
    allow_pipeline.decide(sample_request)
    assert not allow_pipeline.ticket_store.has_ticket(sample_request.user.user_id, sample_request.resource.resource_id)

    emergency_pipeline = make_pipeline(
        threat_sim=0.1,
        cache_candidate=CacheCandidate(hit=False),
        llm_proposal=LLMDecisionProposal(
            proposed_decision=Decision.ALLOW_EMERGENCY,
            confidence=0.9,
            reason_code="LLM_ALLOW_EMERGENCY",
            estimated_cost_usd=0.0,
        ),
    )
    emergency_pipeline.decide(sample_request)
    assert emergency_pipeline.ticket_store.has_ticket(sample_request.user.user_id, sample_request.resource.resource_id)


def test_local_fallback_writes_cache_synchronously_without_kafka(sample_request):
    vector_store = VectorStoreClient(enabled=False)
    pipeline = AccessPipeline(
        policy_version="2026-04-04",
        mode_manager=ModeManager(),
        ingestion=IngestionService(),
        policy=DummyPolicy(),
        embedding=EmbeddingService(
            model_id="test-embedding",
            expected_dim=16,
            _model=type(
                "FakeSentenceTransformer",
                (),
                {
                    "encode_query": staticmethod(lambda text, **kwargs: [0.1] * 16),
                    "get_sentence_embedding_dimension": staticmethod(lambda: 16),
                },
            )(),
        ),
        threat_screen=DummyThreat(0.1),
        cache_lookup=CacheLookupService(vector_store=vector_store),
        validation=DummyValidation(True, 0.81),
        llm_provider=DummyProvider(
            LLMDecisionProposal(
                proposed_decision=Decision.ALLOW,
                confidence=0.92,
                reason_code="LLM_ALLOW",
                estimated_cost_usd=0.0025,
            )
        ),
        shadow_llm_provider=None,
        shadow_sampling_rate=0.0,
        ticket_store=TicketStoreClient(enabled=False),
        events=EventBusClient(enabled=False),
        vector_store=vector_store,
        kpi_tracker=KPITracker(),
    )

    first = pipeline.decide(sample_request)
    second = pipeline.decide(sample_request.model_copy(deep=True))

    assert first.decision == Decision.ALLOW
    assert second.decision == Decision.ALLOW_CACHE
    assert first.estimated_cost_usd == 0.0025
    assert second.estimated_cost_usd == 0.0
