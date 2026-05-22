from __future__ import annotations

from scripts.evaluate_synthetic_cases import (
    EvaluationResult,
    SyntheticCase,
    decision_family,
    evaluate_cases,
    score_response,
    summarize,
)


def make_case(
    *,
    case_id: str = "case-0001",
    category: str = "policy_pass",
    expected_policy_stage: str = "llm",
    expected_decision: str = "ALLOW",
    expected_reason_code: str = "POLICY_PASS_EXPECTED_ALLOW",
    ticket_present: bool = False,
) -> SyntheticCase:
    return SyntheticCase(
        case_id=case_id,
        category=category,
        expected_policy_stage=expected_policy_stage,
        expected_decision=expected_decision,
        expected_reason_code=expected_reason_code,
        expected_decision_basis="test",
        ticket_present=ticket_present,
        request={
            "request_id": case_id,
            "timestamp_utc": "2026-04-14T00:00:00Z",
            "user": {
                "user_id": "user-1",
                "role": "manager",
                "department": "operations",
                "region": "us",
                "clearance_level": 3,
            },
            "context": {
                "ip_address": "10.0.0.1",
                "device_id": "dev-1",
                "session_id": "sess-1",
                "mfa_state": "passed",
                "incident_state": "normal",
            },
            "resource": {
                "resource_type": "document",
                "resource_id": "doc-1",
                "sensitivity": "internal",
            },
            "query": {
                "prompt": "Need access to quarterly finance report",
                "purpose": "monthly close",
            },
        },
        expected_hard_policy={"allow": True, "reason_code": "HARD_POLICY_PASS", "matched_rule": "default_allow"},
        expected_soft_policy={"allow": True, "reason_code": "SOFT_POLICY_PASS", "matched_rule": "default_allow"},
    )


def test_decision_family_maps_allow_like_variants():
    assert decision_family("ALLOW") == "allow"
    assert decision_family("ALLOW_CACHE") == "allow"
    assert decision_family("ALLOW_EMERGENCY") == "allow"
    assert decision_family("DENY") == "deny"
    assert decision_family("ESCALATE_HUMAN") == "escalate"


def test_score_response_marks_false_allow_and_false_deny_correctly():
    deny_case = make_case(expected_decision="DENY", expected_reason_code="MFA_REQUIRED", category="hard_deny_mfa")
    false_allow = score_response(
        deny_case,
        {
            "decision": "ALLOW",
            "reason_code": "POLICY_PASS_EXPECTED_ALLOW",
            "decision_source": "llm",
            "latency_ms": 10,
            "rationale": {
                "summary": "Access is allowed based on the request context.",
                "facts": ["mfa_state=passed", "resource_type=document"],
            },
        },
        skipped=False,
    )
    assert false_allow.false_allow is True
    assert false_allow.decision_exact_match is False
    assert false_allow.rationale_present is True
    assert false_allow.rationale_grounded is True

    allow_case = make_case()
    false_deny = score_response(
        allow_case,
        {
            "decision": "DENY",
            "reason_code": "CLEARANCE_TOO_LOW",
            "decision_source": "hard_rule",
            "latency_ms": 12,
            "rationale": {
                "summary": "Denied because of unsupported facts.",
                "facts": ["fictional_fact=true"],
            },
        },
        skipped=False,
    )
    assert false_deny.false_deny is True
    assert false_deny.decision_family_match is False
    assert false_deny.rationale_present is True
    assert false_deny.rationale_grounded is False


def test_summarize_reports_aggregate_accuracy_and_error_counts():
    results = [
        EvaluationResult(
            case_id="1",
            category="policy_pass",
            expected_policy_stage="llm",
            expected_decision="ALLOW",
            expected_reason_code="POLICY_PASS_EXPECTED_ALLOW",
            actual_decision="ALLOW",
            actual_reason_code="POLICY_PASS_EXPECTED_ALLOW",
            actual_decision_source="llm",
            actual_latency_ms=100,
            actual_cost_usd=0.01,
            actual_confidence=0.9,
            actual_rationale_summary="Allowed because the request matches the current role and sensitivity.",
            actual_rationale_facts=["role=manager", "sensitivity=internal"],
            decision_exact_match=True,
            decision_family_match=True,
            reason_code_match=True,
            rationale_present=True,
            rationale_grounded=True,
            false_allow=False,
            false_deny=False,
            false_escalate=False,
            skipped=False,
            skipped_reason="",
            error="",
        ),
        EvaluationResult(
            case_id="2",
            category="hard_deny_mfa",
            expected_policy_stage="hard_rule",
            expected_decision="DENY",
            expected_reason_code="MFA_REQUIRED",
            actual_decision="ALLOW",
            actual_reason_code="POLICY_PASS_EXPECTED_ALLOW",
            actual_decision_source="llm",
            actual_latency_ms=110,
            actual_cost_usd=0.01,
            actual_confidence=0.9,
            actual_rationale_summary="Allowed despite MFA failure.",
            actual_rationale_facts=["mfa_state=failed"],
            decision_exact_match=False,
            decision_family_match=False,
            reason_code_match=False,
            rationale_present=True,
            rationale_grounded=True,
            false_allow=True,
            false_deny=False,
            false_escalate=False,
            skipped=False,
            skipped_reason="",
            error="",
        ),
        EvaluationResult(
            case_id="3",
            category="soft_emergency",
            expected_policy_stage="soft_rule",
            expected_decision="ALLOW_EMERGENCY",
            expected_reason_code="EMERGENCY_TICKET_VALID",
            actual_decision=None,
            actual_reason_code=None,
            actual_decision_source=None,
            actual_latency_ms=None,
            actual_cost_usd=0.0,
            actual_confidence=None,
            actual_rationale_summary=None,
            actual_rationale_facts=[],
            decision_exact_match=False,
            decision_family_match=False,
            reason_code_match=False,
            rationale_present=False,
            rationale_grounded=False,
            false_allow=False,
            false_deny=False,
            false_escalate=False,
            skipped=True,
            skipped_reason="ticket_store_unavailable",
            error="",
        ),
    ]

    summary = summarize(results)
    assert summary["total_cases"] == 3
    assert summary["evaluated_cases"] == 2
    assert summary["skipped_cases"] == 1
    assert summary["decision_exact_accuracy"] == 0.5
    assert summary["rationale_presence_rate"] == 1.0
    assert summary["rationale_grounded_rate"] == 1.0
    assert summary["false_allow_rate"] == 0.5
    assert summary["skipped_reason_counts"]["ticket_store_unavailable"] == 1


def test_evaluate_cases_primes_soft_rule_and_issues_ticket(monkeypatch):
    case = make_case(
        case_id="soft-1",
        category="soft_emergency",
        expected_policy_stage="soft_rule",
        expected_decision="ALLOW_EMERGENCY",
        expected_reason_code="EMERGENCY_TICKET_VALID",
        ticket_present=True,
    )
    calls: list[dict] = []

    def fake_post_decision(base_url: str, payload: dict, timeout_seconds: float) -> dict:
        calls.append(payload)
        if payload["request_id"].endswith("-eval"):
            return {
                "decision": "ALLOW_EMERGENCY",
                "reason_code": "EMERGENCY_TICKET_VALID",
                "decision_source": "cache",
                "latency_ms": 20,
                "estimated_cost_usd": 0.0,
                "confidence": 0.75,
                "rationale": {
                    "summary": "Emergency access was granted based on the existing ticket.",
                    "facts": ["incident_state=normal", "resource_type=document"],
                },
            }
        return {
            "decision": "ALLOW",
            "reason_code": "POLICY_PASS_EXPECTED_ALLOW",
            "decision_source": "llm",
            "latency_ms": 25,
            "estimated_cost_usd": 0.0,
            "confidence": 0.8,
            "rationale": {
                "summary": "The request passed policy checks.",
                "facts": ["mfa_state=passed", "resource_type=document"],
            },
        }

    class StubTicketStore:
        def __init__(self) -> None:
            self.issued: list[tuple[str, str]] = []

        def issue_ticket(self, user_id: str, resource_id: str, ttl_seconds: int = 900) -> None:
            self.issued.append((user_id, resource_id))

        def has_ticket(self, user_id: str, resource_id: str) -> bool:
            return (user_id, resource_id) in self.issued

    monkeypatch.setattr("scripts.evaluate_synthetic_cases.post_decision", fake_post_decision)
    ticket_store = StubTicketStore()

    results = evaluate_cases(
        [case],
        base_url="http://testserver",
        timeout_seconds=5.0,
        run_id="run-1",
        ticket_store=ticket_store,
    )

    assert len(results) == 1
    assert results[0].decision_exact_match is True
    assert results[0].rationale_present is True
    assert results[0].rationale_grounded is True
    assert len(calls) == 2
    assert calls[0]["request_id"].endswith("-prime")
    assert calls[1]["request_id"].endswith("-eval")
    assert len(ticket_store.issued) == 1
