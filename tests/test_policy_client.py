from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.clients.policy_client import OPAClient
from app.models import ContextInfo, IncidentState, QueryInfo, ResourceInfo, Sensitivity, UserInfo, AccessRequest


def make_request(**overrides) -> AccessRequest:
    user = UserInfo(
        user_id="u-1",
        role="analyst",
        department="finance",
        region="us",
        clearance_level=2,
    )
    context = ContextInfo(
        ip_address="10.1.1.1",
        device_id="dev-1",
        session_id="sess-1",
        mfa_state="passed",
        incident_state=IncidentState.normal,
    )
    resource = ResourceInfo(
        resource_type="document",
        resource_id="doc-1",
        sensitivity=Sensitivity.internal,
    )
    query = QueryInfo(prompt="Need access to report 2026", purpose="monthly close")
    req = AccessRequest(
        request_id="req-1",
        timestamp_utc="2026-04-14T00:00:00Z",
        user=user,
        context=context,
        resource=resource,
        query=query,
    )
    for field, value in overrides.items():
        target, attr = field.split(".", 1)
        setattr(getattr(req, target), attr, value)
    return req


def test_hard_policy_fallback_phase_a_cases():
    client = OPAClient(base_url="", enabled=False)

    assert (
        client.evaluate_hard(
            make_request(**{"resource.sensitivity": Sensitivity.restricted, "user.clearance_level": 1})
        ).reason_code
        == "CLEARANCE_TOO_LOW"
    )
    assert client.evaluate_hard(make_request(**{"resource.sensitivity": Sensitivity.confidential, "user.clearance_level": 2})).reason_code == "CLEARANCE_TOO_LOW"
    assert client.evaluate_hard(make_request(**{"resource.resource_type": "dataset"})).reason_code == "ROLE_RESOURCE_DENIED"
    assert client.evaluate_hard(make_request(**{"user.role": "engineer", "resource.resource_type": "ticket"})).reason_code == "ROLE_RESOURCE_DENIED"
    assert client.evaluate_hard(make_request(**{"user.role": "unknown_role"})).reason_code == "ROLE_RESOURCE_DENIED"
    ok = client.evaluate_hard(make_request(**{"user.role": "engineer", "resource.resource_type": "dataset"}))
    assert ok.allow is True
    assert ok.reason_code == "HARD_POLICY_PASS"


def test_soft_policy_fallback_phase_a_cases():
    client = OPAClient(base_url="", enabled=False)

    elevated_conf = client.evaluate_soft(
        make_request(**{"context.incident_state": IncidentState.elevated, "resource.sensitivity": Sensitivity.confidential})
    )
    assert elevated_conf.allow is False
    assert elevated_conf.reason_code == "INCIDENT_ELEVATED_RESTRICTED_FAST_PATH"
    assert elevated_conf.matched_rule == "incident_elevated_confidential_guard"

    elevated_internal = client.evaluate_soft(
        make_request(**{"context.incident_state": IncidentState.elevated, "resource.sensitivity": Sensitivity.internal})
    )
    assert elevated_internal.allow is True
    assert elevated_internal.reason_code == "SOFT_POLICY_PASS"

    critical = client.evaluate_soft(make_request(**{"context.incident_state": IncidentState.critical}))
    assert critical.allow is False
    assert critical.reason_code == "INCIDENT_CRITICAL"

    out_of_hours = client.evaluate_soft(
        make_request(
            **{
                "context.incident_state": IncidentState.normal,
            }
        ).model_copy(update={"timestamp_utc": datetime(2026, 4, 14, 3, 0, tzinfo=timezone.utc)})
    )
    assert out_of_hours.allow is False
    assert out_of_hours.reason_code == "OUT_OF_HOURS_FAST_PATH_REVIEW"
    assert out_of_hours.matched_rule == "time_window_guard"


def test_rego_files_contain_phase_a_reason_codes_and_rule_names():
    hard_rego = Path("policies/hard.rego").read_text(encoding="utf-8")
    soft_rego = Path("policies/soft.rego").read_text(encoding="utf-8")

    for token in [
        "MFA_REQUIRED",
        "SESSION_INVALID",
        "CLEARANCE_TOO_LOW",
        "ROLE_RESOURCE_DENIED",
        "mfa_required",
        "session_required",
        "clearance_guard",
        "role_resource_guard",
        "HARD_POLICY_PASS",
    ]:
        assert token in hard_rego

    assert hard_rego.index("MFA_REQUIRED") < hard_rego.index("SESSION_INVALID") < hard_rego.index("CLEARANCE_TOO_LOW") < hard_rego.index("ROLE_RESOURCE_DENIED")

    for token in [
        "INCIDENT_CRITICAL",
        "INCIDENT_ELEVATED_RESTRICTED_FAST_PATH",
        "OUT_OF_HOURS_FAST_PATH_REVIEW",
        "incident_guard",
        "incident_elevated_confidential_guard",
        "time_window_guard",
        "SOFT_POLICY_PASS",
        "default_allow",
    ]:
        assert token in soft_rego
