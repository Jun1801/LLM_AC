from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.clients.policy_client import OPAClient, ROLE_RESOURCE_ALLOWLIST
from app.models import AccessRequest, ContextInfo, IncidentState, QueryInfo, ResourceInfo, Sensitivity, UserInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_PATH = REPO_ROOT / "eval" / "phase_a_synthetic_cases.jsonl"
DEFAULT_SUMMARY_PATH = REPO_ROOT / "eval" / "phase_a_synthetic_cases_summary.json"

ROLE_DEPARTMENTS = {
    "analyst": "finance",
    "manager": "operations",
    "auditor": "security",
    "engineer": "engineering",
    "security_analyst": "security",
    "hr_partner": "hr",
    "legal_counsel": "legal",
}

ROLE_BASE_CLEARANCE = {
    "analyst": 2,
    "manager": 3,
    "auditor": 3,
    "engineer": 2,
    "security_analyst": 3,
    "hr_partner": 2,
    "legal_counsel": 3,
}

# Roles whose base clearance meets the confidential minimum (3)
HIGH_CLEARANCE_ROLES = [r for r, c in ROLE_BASE_CLEARANCE.items() if c >= 3]

RESOURCE_ARTIFACTS = {
    "document": [
        "quarterly finance report",
        "vendor contract archive",
        "deployment readiness checklist",
    ],
    "report": [
        "campaign performance report",
        "inventory variance report",
        "staffing review report",
    ],
    "dashboard": [
        "service reliability dashboard",
        "customer retention dashboard",
        "headcount planning dashboard",
    ],
    "dataset": [
        "payroll adjustment log",
        "security audit log",
        "policy exception register",
    ],
    "ticket": [
        "procurement approval ticket",
        "incident exception ticket",
        "vendor escalation ticket",
    ],
}

PURPOSES = {
    "finance": ["monthly close", "forecast review"],
    "operations": ["operational planning", "exception handling"],
    "security": ["audit preparation", "incident follow-up"],
    "engineering": ["release planning", "service review"],
    "hr": ["staffing review", "onboarding support"],
    "legal": ["contract review", "policy review"],
}

PROMPT_TEMPLATES = [
    "Need access to {artifact}",
    "Request access to the {artifact}",
    "Need the {artifact} for {purpose}",
    "Please grant access to {artifact} for {purpose}",
    "I need {artifact} access to support {purpose}",
    "Can I get access to {artifact}?",
    "Requesting {artifact} for {purpose}",
    "Grant me access to the {artifact} for {purpose}",
]

# Timestamp used for in-hours cases (10:00 UTC, outside 02–06 high-risk window)
_IN_HOURS_TS = datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc)
# Timestamp used for out-of-hours cases (03:00 UTC, inside 02–06 high-risk window)
_OUT_OF_HOURS_TS = datetime(2026, 4, 14, 3, 0, tzinfo=timezone.utc)


@dataclass
class LabeledCase:
    case_id: str
    category: str
    expected_policy_stage: str
    expected_decision: str
    expected_reason_code: str
    expected_decision_basis: str
    ticket_present: bool
    request: dict
    expected_hard_policy: dict
    expected_soft_policy: dict | None


def make_request(
    case_id: str,
    role: str,
    resource_type: str,
    sensitivity: Sensitivity,
    *,
    clearance_level: int,
    incident_state: IncidentState = IncidentState.normal,
    mfa_state: str = "passed",
    session_id: str = "sess-1",
    department: str | None = None,
    prompt_variant: int = 0,
    timestamp_utc: datetime = _IN_HOURS_TS,
) -> AccessRequest:
    department = department or ROLE_DEPARTMENTS.get(role, "external")
    artifact = RESOURCE_ARTIFACTS[resource_type][prompt_variant % len(RESOURCE_ARTIFACTS[resource_type])]
    purpose_options = PURPOSES.get(department, ["general review"])
    purpose = purpose_options[prompt_variant % len(purpose_options)]
    prompt = PROMPT_TEMPLATES[prompt_variant % len(PROMPT_TEMPLATES)].format(artifact=artifact, purpose=purpose)
    return AccessRequest(
        request_id=case_id,
        timestamp_utc=timestamp_utc,
        user=UserInfo(
            user_id=f"user-{role}-{case_id}",
            role=role,
            department=department,
            region="us",
            clearance_level=clearance_level,
        ),
        context=ContextInfo(
            ip_address="10.20.30.40",
            device_id=f"device-{case_id}",
            session_id=session_id,
            mfa_state=mfa_state,
            incident_state=incident_state,
        ),
        resource=ResourceInfo(
            resource_type=resource_type,
            resource_id=f"{resource_type}-{case_id}",
            sensitivity=sensitivity,
        ),
        query=QueryInfo(prompt=prompt, purpose=purpose),
    )


def label_request(req: AccessRequest, *, ticket_present: bool) -> tuple[dict, dict | None, str, str, str, str]:
    policy = OPAClient(base_url="", enabled=False)
    hard = policy.evaluate_hard(req)
    hard_dict = hard.model_dump()
    if not hard.allow:
        return hard_dict, None, "hard_rule", "DENY", hard.reason_code, "hard_rule"
    soft = policy.evaluate_soft(req)
    soft_dict = soft.model_dump()
    if not soft.allow:
        if ticket_present:
            return hard_dict, soft_dict, "soft_rule", "ALLOW_EMERGENCY", "EMERGENCY_TICKET_VALID", "soft_rule_ticket"
        return hard_dict, soft_dict, "soft_rule", "ESCALATE_HUMAN", soft.reason_code, "soft_rule_review"
    return hard_dict, soft_dict, "llm", "ALLOW", "POLICY_PASS_EXPECTED_ALLOW", "policy_pass_assumption"


def choose_disallowed_resource_type(role: str) -> str:
    for resource_type in RESOURCE_ARTIFACTS:
        if resource_type not in ROLE_RESOURCE_ALLOWLIST.get(role, set()):
            return resource_type
    return "ticket"


def build_cases() -> list[LabeledCase]:
    cases: list[LabeledCase] = []
    case_index = 0

    def append_case(
        category: str,
        req: AccessRequest,
        *,
        ticket_present: bool = False,
    ) -> None:
        nonlocal case_index
        case_index += 1
        hard, soft, stage, decision, reason_code, basis = label_request(req, ticket_present=ticket_present)
        cases.append(
            LabeledCase(
                case_id=f"case-{case_index:04d}",
                category=category,
                expected_policy_stage=stage,
                expected_decision=decision,
                expected_reason_code=reason_code,
                expected_decision_basis=basis,
                ticket_present=ticket_present,
                request=req.model_dump(mode="json"),
                expected_hard_policy=hard,
                expected_soft_policy=soft,
            )
        )

    roles = list(ROLE_RESOURCE_ALLOWLIST.keys())

    # ── policy_pass: public sensitivity ──────────────────────────────────────
    # sensitivity=public requires clearance=0; any authenticated user passes.
    for role in roles:
        allowed_resource_types = sorted(ROLE_RESOURCE_ALLOWLIST[role])
        for idx, resource_type in enumerate(allowed_resource_types):
            req = make_request(
                case_id=f"pass-public-{role}-{resource_type}-{idx}",
                role=role,
                resource_type=resource_type,
                sensitivity=Sensitivity.public,
                clearance_level=1,
                incident_state=IncidentState.normal,
                prompt_variant=idx,
            )
            append_case("policy_pass_public", req)

    # ── policy_pass: internal sensitivity ────────────────────────────────────
    # sensitivity=internal requires clearance>=1; base clearances (2–3) all pass.
    for role in roles:
        allowed_resource_types = sorted(ROLE_RESOURCE_ALLOWLIST[role])
        for idx, resource_type in enumerate(allowed_resource_types):
            req = make_request(
                case_id=f"pass-{role}-{resource_type}-{idx}",
                role=role,
                resource_type=resource_type,
                sensitivity=Sensitivity.internal,
                clearance_level=ROLE_BASE_CLEARANCE[role],
                incident_state=IncidentState.normal,
                prompt_variant=idx,
            )
            append_case("policy_pass", req)

    # ── policy_pass: restricted sensitivity ──────────────────────────────────
    # sensitivity=restricted requires clearance>=2. All base clearances (2–3) satisfy this.
    for role in roles:
        allowed_resource_types = sorted(ROLE_RESOURCE_ALLOWLIST[role])
        for idx, resource_type in enumerate(allowed_resource_types):
            req = make_request(
                case_id=f"pass-restricted-{role}-{resource_type}-{idx}",
                role=role,
                resource_type=resource_type,
                sensitivity=Sensitivity.restricted,
                clearance_level=max(ROLE_BASE_CLEARANCE[role], 2),
                incident_state=IncidentState.normal,
                prompt_variant=idx + 1,
            )
            append_case("policy_pass_restricted", req)

    # ── policy_pass: confidential sensitivity, normal incident ────────────────
    # sensitivity=confidential requires clearance>=3, incident must not be elevated/critical.
    # Only roles with base clearance=3 are used (manager, auditor, security_analyst, legal_counsel).
    for role in HIGH_CLEARANCE_ROLES:
        allowed_resource_types = sorted(ROLE_RESOURCE_ALLOWLIST[role])
        for idx, resource_type in enumerate(allowed_resource_types):
            req = make_request(
                case_id=f"pass-confidential-{role}-{resource_type}-{idx}",
                role=role,
                resource_type=resource_type,
                sensitivity=Sensitivity.confidential,
                clearance_level=3,
                incident_state=IncidentState.normal,
                prompt_variant=idx + 2,
            )
            append_case("policy_pass_confidential", req)

    # ── policy_pass: elevated incident, non-confidential sensitivity ──────────
    # Elevated incident only blocks confidential resources (soft rule).
    # internal/restricted + elevated incident must still ALLOW.
    for role in roles:
        resource_type = sorted(ROLE_RESOURCE_ALLOWLIST[role])[0]
        req = make_request(
            case_id=f"pass-elevated-internal-{role}",
            role=role,
            resource_type=resource_type,
            sensitivity=Sensitivity.internal,
            clearance_level=ROLE_BASE_CLEARANCE[role],
            incident_state=IncidentState.elevated,
            prompt_variant=1,
        )
        append_case("policy_pass_elevated_internal", req)

    # ── policy_pass: elevated incident, restricted sensitivity ───────────────
    for role in roles:
        resource_type = sorted(ROLE_RESOURCE_ALLOWLIST[role])[0]
        req = make_request(
            case_id=f"pass-elevated-restricted-{role}",
            role=role,
            resource_type=resource_type,
            sensitivity=Sensitivity.restricted,
            clearance_level=max(ROLE_BASE_CLEARANCE[role], 2),
            incident_state=IncidentState.elevated,
            prompt_variant=3,
        )
        append_case("policy_pass_elevated_restricted", req)

    # ── hard_deny: MFA failed ─────────────────────────────────────────────────
    for role in roles:
        resource_type = sorted(ROLE_RESOURCE_ALLOWLIST[role])[0]
        req = make_request(
            case_id=f"mfa-{role}",
            role=role,
            resource_type=resource_type,
            sensitivity=Sensitivity.internal,
            clearance_level=ROLE_BASE_CLEARANCE[role],
            mfa_state="failed",
            prompt_variant=2,
        )
        append_case("hard_deny_mfa", req)

    # ── hard_deny: invalid session ────────────────────────────────────────────
    for role in roles:
        resource_type = sorted(ROLE_RESOURCE_ALLOWLIST[role])[0]
        req = make_request(
            case_id=f"session-{role}",
            role=role,
            resource_type=resource_type,
            sensitivity=Sensitivity.internal,
            clearance_level=ROLE_BASE_CLEARANCE[role],
            session_id="",
            prompt_variant=3,
        )
        append_case("hard_deny_session", req)

    # ── hard_deny: clearance too low ──────────────────────────────────────────
    # clearance=0 for internal (requires >=1)
    for role in roles:
        resource_type = sorted(ROLE_RESOURCE_ALLOWLIST[role])[0]
        req = make_request(
            case_id=f"clearance-zero-internal-{role}",
            role=role,
            resource_type=resource_type,
            sensitivity=Sensitivity.internal,
            clearance_level=0,
            prompt_variant=0,
        )
        append_case("hard_deny_clearance_internal", req)

    # clearance=1 for restricted (requires >=2)
    for role in roles:
        resource_type = sorted(ROLE_RESOURCE_ALLOWLIST[role])[0]
        req = make_request(
            case_id=f"clearance-restricted-{role}",
            role=role,
            resource_type=resource_type,
            sensitivity=Sensitivity.restricted,
            clearance_level=1,
            prompt_variant=0,
        )
        append_case("hard_deny_clearance", req)

    # clearance=2 for confidential (requires >=3)
    for role in roles:
        resource_type = sorted(ROLE_RESOURCE_ALLOWLIST[role])[0]
        req = make_request(
            case_id=f"clearance-confidential-{role}",
            role=role,
            resource_type=resource_type,
            sensitivity=Sensitivity.confidential,
            clearance_level=2,
            prompt_variant=1,
        )
        append_case("hard_deny_clearance", req)

    # ── hard_deny: role not permitted for resource type ───────────────────────
    for role in roles:
        disallowed_resource_types = [
            resource_type for resource_type in sorted(RESOURCE_ARTIFACTS) if resource_type not in ROLE_RESOURCE_ALLOWLIST[role]
        ]
        for idx, disallowed in enumerate(disallowed_resource_types[:2]):
            req = make_request(
                case_id=f"role-deny-{role}-{disallowed}-{idx}",
                role=role,
                resource_type=disallowed,
                sensitivity=Sensitivity.internal,
                clearance_level=max(ROLE_BASE_CLEARANCE[role], 3),
                prompt_variant=idx + 2,
            )
            append_case("hard_deny_role_resource", req)

    # ── hard_deny: unknown role ───────────────────────────────────────────────
    for idx, resource_type in enumerate(sorted(RESOURCE_ARTIFACTS.keys())):
        req = make_request(
            case_id=f"unknown-role-{resource_type}-{idx}",
            role="contractor",
            resource_type=resource_type,
            sensitivity=Sensitivity.internal,
            clearance_level=3,
            department="external",
            prompt_variant=idx,
        )
        append_case("hard_deny_unknown_role", req)

    # ── soft_deny: critical incident ─────────────────────────────────────────
    # incident=critical blocks all requests regardless of sensitivity (soft rule).
    for role in roles:
        resource_type = sorted(ROLE_RESOURCE_ALLOWLIST[role])[0]
        req = make_request(
            case_id=f"soft-critical-{role}",
            role=role,
            resource_type=resource_type,
            sensitivity=Sensitivity.internal,
            clearance_level=ROLE_BASE_CLEARANCE[role],
            incident_state=IncidentState.critical,
            prompt_variant=4,
        )
        append_case("soft_deny_critical", req)

    # ── soft_deny: out-of-hours access (02:00–06:00 UTC) ─────────────────────
    # The high-risk window guard blocks all requests timestamped between 02 and 06 UTC.
    for role in roles:
        resource_type = sorted(ROLE_RESOURCE_ALLOWLIST[role])[0]
        req = make_request(
            case_id=f"soft-ooh-{role}",
            role=role,
            resource_type=resource_type,
            sensitivity=Sensitivity.internal,
            clearance_level=ROLE_BASE_CLEARANCE[role],
            incident_state=IncidentState.normal,
            prompt_variant=5,
            timestamp_utc=_OUT_OF_HOURS_TS,
        )
        append_case("soft_deny_out_of_hours", req)

    # ── soft_deny: elevated incident + confidential sensitivity ──────────────
    # (aka soft_review) – no ticket present, expects ESCALATE_HUMAN
    for role in roles:
        for idx, resource_type in enumerate(sorted(ROLE_RESOURCE_ALLOWLIST[role])[:2]):
            req = make_request(
                case_id=f"soft-review-{role}-{resource_type}-{idx}",
                role=role,
                resource_type=resource_type,
                sensitivity=Sensitivity.confidential,
                clearance_level=3,
                incident_state=IncidentState.elevated,
                prompt_variant=idx,
            )
            append_case("soft_review", req, ticket_present=False)

    # ── soft_emergency: elevated + confidential with valid ticket ─────────────
    for role in roles:
        for idx, resource_type in enumerate(sorted(ROLE_RESOURCE_ALLOWLIST[role])[:2]):
            req = make_request(
                case_id=f"soft-emergency-{role}-{resource_type}-{idx}",
                role=role,
                resource_type=resource_type,
                sensitivity=Sensitivity.confidential,
                clearance_level=3,
                incident_state=IncidentState.elevated,
                prompt_variant=idx + 1,
            )
            append_case("soft_emergency", req, ticket_present=True)

    # ── near_miss_soft: same role/clearance/resource, different incident_state ─
    # Case A (allow): confidential + clearance=3 + incident=normal → ALLOW
    # Case B (deny):  identical attributes except incident=elevated → ESCALATE_HUMAN
    # These share the same semantic embedding space and test whether the cache
    # correctly defers to soft-policy when incident_state changes the decision.
    for role in HIGH_CLEARANCE_ROLES:
        resource_type = sorted(ROLE_RESOURCE_ALLOWLIST[role])[0]
        req_allow = make_request(
            case_id=f"near-miss-soft-allow-{role}",
            role=role,
            resource_type=resource_type,
            sensitivity=Sensitivity.confidential,
            clearance_level=3,
            incident_state=IncidentState.normal,
            prompt_variant=6,
        )
        append_case("near_miss_soft_allow", req_allow)

        req_deny = make_request(
            case_id=f"near-miss-soft-deny-{role}",
            role=role,
            resource_type=resource_type,
            sensitivity=Sensitivity.confidential,
            clearance_level=3,
            incident_state=IncidentState.elevated,
            prompt_variant=6,
        )
        append_case("near_miss_soft_deny", req_deny, ticket_present=False)

    return cases


def build_summary(cases: list[LabeledCase]) -> dict:
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "label_source": "phase_a_policy_matrix",
        "assumptions": {
            "policy_pass_decision": "ALLOW",
            "policy_pass_reason_code": "POLICY_PASS_EXPECTED_ALLOW",
            "soft_review_without_ticket_decision": "ESCALATE_HUMAN",
            "soft_review_with_ticket_decision": "ALLOW_EMERGENCY",
            "sensitivity_min_clearance": {
                "public": 0,
                "internal": 1,
                "restricted": 2,
                "confidential": 3,
            },
        },
        "case_count": len(cases),
        "category_counts": dict(Counter(case.category for case in cases)),
        "expected_policy_stage_counts": dict(Counter(case.expected_policy_stage for case in cases)),
        "expected_decision_counts": dict(Counter(case.expected_decision for case in cases)),
        "expected_reason_code_counts": dict(Counter(case.expected_reason_code for case in cases)),
    }


def write_cases(cases: list[LabeledCase], dataset_path: Path, summary_path: Path) -> None:
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    with dataset_path.open("w", encoding="utf-8", newline="\n") as fh:
        for case in cases:
            fh.write(json.dumps(asdict(case), ensure_ascii=True) + "\n")
    summary_path.write_text(json.dumps(build_summary(cases), indent=2), encoding="utf-8")


def main() -> None:
    cases = build_cases()
    write_cases(cases, DEFAULT_DATASET_PATH, DEFAULT_SUMMARY_PATH)
    summary = build_summary(cases)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
