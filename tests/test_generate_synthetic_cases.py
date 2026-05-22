from __future__ import annotations

from collections import Counter

from app.clients.policy_client import OPAClient
from app.models import AccessRequest
from scripts.generate_synthetic_cases import build_cases


def test_generated_cases_cover_expected_categories_and_count():
    cases = build_cases()
    assert len(cases) >= 100

    categories = Counter(case.category for case in cases)
    for category in [
        "policy_pass",
        "hard_deny_mfa",
        "hard_deny_session",
        "hard_deny_clearance",
        "hard_deny_role_resource",
        "hard_deny_unknown_role",
        "soft_review",
        "soft_emergency",
    ]:
        assert categories[category] > 0


def test_generated_labels_match_phase_a_policy_logic():
    cases = build_cases()
    policy = OPAClient(base_url="", enabled=False)

    for case in cases:
        req = AccessRequest.model_validate(case.request)
        hard = policy.evaluate_hard(req)
        assert hard.model_dump() == case.expected_hard_policy
        if not hard.allow:
            assert case.expected_policy_stage == "hard_rule"
            assert case.expected_decision == "DENY"
            assert case.expected_reason_code == hard.reason_code
            assert case.expected_soft_policy is None
            continue

        soft = policy.evaluate_soft(req)
        assert soft.model_dump() == case.expected_soft_policy
        if not soft.allow:
            assert case.expected_policy_stage == "soft_rule"
            if case.ticket_present:
                assert case.expected_decision == "ALLOW_EMERGENCY"
                assert case.expected_reason_code == "EMERGENCY_TICKET_VALID"
            else:
                assert case.expected_decision == "ESCALATE_HUMAN"
                assert case.expected_reason_code == soft.reason_code
        else:
            assert case.expected_policy_stage == "llm"
            assert case.expected_decision == "ALLOW"
            assert case.expected_reason_code == "POLICY_PASS_EXPECTED_ALLOW"
