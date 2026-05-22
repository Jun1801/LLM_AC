from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.models import Decision, LLMDecisionProposal, LLMRationale, LLMUsage
from app.rationale import build_grounding_facts, grounded_facts_only

_SYSTEM_PROMPT = """\
You are a stateless access-control decision engine. Evaluate the provided facts and return strict JSON.

IMPORTANT — SENSITIVITY LABELS:
The sensitivity field uses internal tiers: public, internal, restricted, confidential.
A user with sufficient clearance_level CAN access a "confidential" resource if no other rule blocks it.
Do NOT deny based on sensitivity alone — only H3 or S2 (defined below) can involve sensitivity.

HARD RULES — return DENY immediately, no exceptions:
H1  mfa_state != "passed"
    → DENY, reason_code: MFA_REQUIRED
H2  session_present = "false"
    → DENY, reason_code: SESSION_INVALID
H3  clearance_level below sensitivity minimum (public=0, internal=1, restricted=2, confidential=3)
    → DENY, reason_code: CLEARANCE_TOO_LOW
H4  role not permitted for resource_type:
      analyst          → document, report, dashboard
      manager          → document, report, dashboard, ticket
      auditor          → document, report, dataset, dashboard
      engineer         → document, dashboard, dataset
      security_analyst → document, dataset, dashboard, ticket
      hr_partner       → document, report, dataset
      legal_counsel    → document, dataset, ticket
    → DENY, reason_code: ROLE_RESOURCE_DENIED

MANDATORY ESCALATION CONDITIONS — checked after hard rules pass; these override ALLOW:
S1  incident_state = "critical"
    → MUST return ESCALATE_HUMAN, reason_code: INCIDENT_CRITICAL
    → Exception: return ALLOW_EMERGENCY only if purpose explicitly describes active incident
      response (e.g. "responding to outage", "investigating the breach", "incident containment").
      Routine purposes — "monthly close", "forecast review", "audit preparation", "staffing review",
      "contract review", "release planning", "service review", "onboarding support" — do NOT qualify.
      When in doubt, return ESCALATE_HUMAN.
S2  incident_state = "elevated" AND sensitivity = "confidential"
    → MUST return ESCALATE_HUMAN, reason_code: INCIDENT_ELEVATED_RESTRICTED_FAST_PATH
    → Exception: return ALLOW_EMERGENCY only if access is required to resolve the active incident.
    S2 requires sensitivity to be exactly "confidential" — the top tier.
    sensitivity = "restricted" does NOT satisfy S2. sensitivity = "internal" does NOT satisfy S2.
    elevated + restricted → no escalation → DEFAULT ALLOW
    elevated + internal  → no escalation → DEFAULT ALLOW
    elevated + public    → no escalation → DEFAULT ALLOW

DEFAULT ALLOW: no hard rule and no escalation condition matched → ALLOW, reason_code: POLICY_PASS

OUTPUT (strict JSON, no other text — keys must appear in this exact order):
{
  "step1_hard_rule_check": "<evaluate H1, H2, H3, H4 in order — state which fired (e.g. 'H3 fires: clearance_level=1 < confidential minimum=3') or 'none fired'>",
  "step2_escalation_check": "<if step1=none fired: read incident_state and sensitivity from facts. Check S1: does incident_state equal exactly 'critical'? Check S2: does incident_state equal exactly 'elevated' AND sensitivity equal exactly 'confidential'? sensitivity='restricted' or 'internal' do NOT trigger S2. State 'S1 fires', 'S2 fires', or 'no escalation condition triggered'>",
  "rationale_facts": ["<exact verbatim strings copied from allowed_facts — no paraphrasing>"],
  "rationale_summary": "<one sentence citing which rule fired and the deciding fact>",
  "confidence": "<1.0 for hard-rule outcomes, 0.9 for soft-rule outcomes, 0.85 for ALLOW>",
  "reason_code": "<exact code from the matched rule — do NOT invent new codes>",
  "proposed_decision": "ALLOW" | "DENY" | "ESCALATE_HUMAN" | "ALLOW_EMERGENCY"
}"""


def _parse_confidence(raw: object, default: float = 0.5) -> float:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


class DecisionProvider(Protocol):
    def evaluate(self, structured_facts: dict[str, Any]) -> LLMDecisionProposal:
        ...

    def ping(self) -> tuple[bool, str]:
        ...


@dataclass
class OpenAIDecisionProvider:
    api_key: str
    model: str
    input_cost_per_1m_tokens: float = 0.15
    output_cost_per_1m_tokens: float = 0.60

    def _fallback_proposal(self, structured_facts: dict[str, Any], *, confidence: float, reason_code: str) -> LLMDecisionProposal:
        grounding_facts = build_grounding_facts(structured_facts)
        return LLMDecisionProposal(
            proposed_decision=Decision.ESCALATE_HUMAN,
            confidence=confidence,
            reason_code=reason_code,
            llm_usage=LLMUsage(),
            estimated_cost_usd=0.0,
            rationale=LLMRationale(
                summary=f"Provider fallback triggered: {reason_code}.",
                facts=grounding_facts[:4],
            ),
        )

    def evaluate(self, structured_facts: dict[str, Any]) -> LLMDecisionProposal:
        grounding_facts = build_grounding_facts(structured_facts)
        if not self.api_key:
            return self._fallback_proposal(structured_facts, confidence=0.4, reason_code="OPENAI_UNCONFIGURED")
        try:
            from openai import OpenAI  # type: ignore
        except Exception:  # noqa: BLE001
            return self._fallback_proposal(structured_facts, confidence=0.4, reason_code="OPENAI_SDK_MISSING")

        client = OpenAI(api_key=self.api_key)
        user_message = f"Facts: {json.dumps(structured_facts)}\nallowed_facts: {json.dumps(grounding_facts)}"
        try:
            completion = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            raw = completion.choices[0].message.content or "{}"
            parsed = json.loads(raw)
            proposed = Decision(parsed.get("proposed_decision", "ESCALATE_HUMAN"))
            usage = getattr(completion, "usage", None)
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            total_tokens = int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0)
            estimated_cost = (
                (prompt_tokens / 1_000_000) * self.input_cost_per_1m_tokens
                + (completion_tokens / 1_000_000) * self.output_cost_per_1m_tokens
            )
            rationale_facts = grounded_facts_only(parsed.get("rationale_facts"), grounding_facts)
            return LLMDecisionProposal(
                proposed_decision=proposed,
                confidence=_parse_confidence(parsed.get("confidence"), default=0.5),
                reason_code=str(parsed.get("reason_code", "OPENAI_EVALUATED")),
                llm_usage=LLMUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                ),
                estimated_cost_usd=estimated_cost,
                rationale=LLMRationale(
                    summary=str(parsed.get("rationale_summary", "")).strip() or None,
                    facts=rationale_facts,
                ),
            )
        except Exception:  # noqa: BLE001
            return self._fallback_proposal(structured_facts, confidence=0.3, reason_code="OPENAI_EVAL_FAILED")

    def ping(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "OPENAI_API_KEY missing"
        return True, "configured"


@dataclass
class VLLMDecisionProvider:
    base_url: str
    model: str = "vllm-model"
    input_cost_per_1m_tokens: float = 0.0
    output_cost_per_1m_tokens: float = 0.0

    def _fallback_proposal(self, structured_facts: dict[str, Any], *, reason_code: str) -> LLMDecisionProposal:
        grounding_facts = build_grounding_facts(structured_facts)
        return LLMDecisionProposal(
            proposed_decision=Decision.ESCALATE_HUMAN,
            confidence=0.3,
            reason_code=reason_code,
            llm_usage=LLMUsage(),
            estimated_cost_usd=0.0,
            rationale=LLMRationale(
                summary=f"Provider fallback triggered: {reason_code}.",
                facts=grounding_facts[:4],
            ),
        )

    def evaluate(self, structured_facts: dict[str, Any]) -> LLMDecisionProposal:
        grounding_facts = build_grounding_facts(structured_facts)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps({"facts": structured_facts, "allowed_facts": grounding_facts}),
                },
            ],
            "temperature": 0,
        }
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(f"{self.base_url}/chat/completions", json=payload)
                resp.raise_for_status()
                body = resp.json()
                content = body["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                usage_data = body.get("usage", {}) or {}
                prompt_tokens = int(usage_data.get("prompt_tokens", 0) or 0)
                completion_tokens = int(usage_data.get("completion_tokens", 0) or 0)
                total_tokens = int(usage_data.get("total_tokens", prompt_tokens + completion_tokens) or 0)
                estimated_cost = (
                    (prompt_tokens / 1_000_000) * self.input_cost_per_1m_tokens
                    + (completion_tokens / 1_000_000) * self.output_cost_per_1m_tokens
                )
                rationale_facts = grounded_facts_only(parsed.get("rationale_facts"), grounding_facts)
            return LLMDecisionProposal(
                proposed_decision=Decision(parsed.get("proposed_decision", "ESCALATE_HUMAN")),
                confidence=_parse_confidence(parsed.get("confidence"), default=0.5),
                reason_code=str(parsed.get("reason_code", "VLLM_EVALUATED")),
                llm_usage=LLMUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                ),
                estimated_cost_usd=estimated_cost,
                rationale=LLMRationale(
                    summary=str(parsed.get("rationale_summary", "")).strip() or None,
                    facts=rationale_facts,
                ),
            )
        except Exception:  # noqa: BLE001
            return self._fallback_proposal(structured_facts, reason_code="VLLM_EVAL_FAILED")

    def ping(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(f"{self.base_url}/models")
                return resp.status_code < 500, f"status={resp.status_code}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
