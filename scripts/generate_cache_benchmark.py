"""Generate phase_b_cache_benchmark.jsonl — anchor/variant pairs for semantic cache evaluation.

Dataset structure
-----------------
phase="anchor"   : 24 clean ALLOW cases (one per role×resource_type) sent first to warm cache.
phase="variant"  : 4 variant types per anchor that test cache precision and safety:

  paraphrase                  – same artifact, different sentence structure
                                → expects ALLOW; tests cache correctly serves the right decision
  artifact_swap               – same template, second artifact within the same resource_type
                                → expects ALLOW; tests similarity threshold boundary
  near_miss_incident          – identical prompt, but incident_state=critical
                                → expects ESCALATE_HUMAN; _handle_cache_hit re-evaluates soft
                                  policy before returning ALLOW_CACHE, so the request correctly
                                  falls through to LLM — 0% false-allow rate confirms safety
  near_miss_elevated_conf     – identical prompt, but incident=elevated + sensitivity=confidential
                                (HIGH_CLEARANCE_ROLES only, clearance stays at 3)
                                → expects ESCALATE_HUMAN; same soft-policy re-evaluation applies

Architecture note: incident_state and sensitivity are NOT in the cache metadata filter, but
_handle_cache_hit() calls evaluate_soft(req) on every hit before returning ALLOW_CACHE.
A 0% false-allow rate on near-miss variants confirms this guarantee holds.
A non-zero rate signals a pipeline regression in the soft-policy re-evaluation path.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.clients.policy_client import ROLE_RESOURCE_ALLOWLIST
from app.models import AccessRequest, ContextInfo, IncidentState, QueryInfo, ResourceInfo, Sensitivity, UserInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_PATH = REPO_ROOT / "eval" / "phase_b_cache_benchmark.jsonl"
DEFAULT_SUMMARY_PATH = REPO_ROOT / "eval" / "phase_b_cache_benchmark_summary.json"

_IN_HOURS_TS = datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc)

ROLE_DEPARTMENTS: dict[str, str] = {
    "analyst": "finance",
    "manager": "operations",
    "auditor": "security",
    "engineer": "engineering",
    "security_analyst": "security",
    "hr_partner": "hr",
    "legal_counsel": "legal",
}

ROLE_BASE_CLEARANCE: dict[str, int] = {
    "analyst": 2,
    "manager": 3,
    "auditor": 3,
    "engineer": 2,
    "security_analyst": 3,
    "hr_partner": 2,
    "legal_counsel": 3,
}

HIGH_CLEARANCE_ROLES = {r for r, c in ROLE_BASE_CLEARANCE.items() if c >= 3}

RESOURCE_ARTIFACTS: dict[str, list[str]] = {
    "document": ["quarterly finance report", "vendor contract archive", "deployment readiness checklist"],
    "report": ["campaign performance report", "inventory variance report", "staffing review report"],
    "dashboard": ["service reliability dashboard", "customer retention dashboard", "headcount planning dashboard"],
    "dataset": ["payroll adjustment log", "security audit log", "policy exception register"],
    "ticket": ["procurement approval ticket", "incident exception ticket", "vendor escalation ticket"],
}

PURPOSES: dict[str, list[str]] = {
    "finance": ["monthly close", "forecast review"],
    "operations": ["operational planning", "exception handling"],
    "security": ["audit preparation", "incident follow-up"],
    "engineering": ["release planning", "service review"],
    "hr": ["staffing review", "onboarding support"],
    "legal": ["contract review", "policy review"],
}


@dataclass
class CacheBenchmarkCase:
    case_id: str
    phase: str          # "anchor" | "variant"
    anchor_id: str | None
    variant_type: str | None
    expected_decision: str
    expected_reason_code: str
    note: str
    request: dict


def _user(case_id: str, role: str) -> UserInfo:
    return UserInfo(
        user_id=f"user-{role}-{case_id}",
        role=role,
        department=ROLE_DEPARTMENTS.get(role, "external"),
        region="us",
        clearance_level=ROLE_BASE_CLEARANCE[role],
    )


def _context(case_id: str, incident_state: IncidentState = IncidentState.normal) -> ContextInfo:
    return ContextInfo(
        ip_address="10.20.30.40",
        device_id=f"device-{case_id}",
        session_id="sess-bench-1",
        mfa_state="passed",
        incident_state=incident_state,
    )


def _resource(case_id: str, resource_type: str, sensitivity: Sensitivity = Sensitivity.internal) -> ResourceInfo:
    return ResourceInfo(
        resource_type=resource_type,
        resource_id=f"{resource_type}-{case_id}",
        sensitivity=sensitivity,
    )


def _anchor_prompt(role: str, resource_type: str) -> tuple[str, str]:
    """Return (prompt, purpose) for the anchor case."""
    artifact = RESOURCE_ARTIFACTS[resource_type][0]
    purpose = PURPOSES.get(ROLE_DEPARTMENTS.get(role, "external"), ["general review"])[0]
    return f"Need access to {artifact}", purpose


def _paraphrase_prompt(role: str, resource_type: str) -> tuple[str, str]:
    """Different wording, same artifact — should produce high cosine similarity."""
    artifact = RESOURCE_ARTIFACTS[resource_type][0]
    purpose = PURPOSES.get(ROLE_DEPARTMENTS.get(role, "external"), ["general review"])[0]
    return f"I need {artifact} access to support {purpose}", purpose


def _artifact_swap_prompt(role: str, resource_type: str) -> tuple[str, str]:
    """Same template as anchor, second artifact — moderate similarity."""
    artifact = RESOURCE_ARTIFACTS[resource_type][1]
    purpose = PURPOSES.get(ROLE_DEPARTMENTS.get(role, "external"), ["general review"])[0]
    return f"Need access to {artifact}", purpose


def build_cases() -> list[CacheBenchmarkCase]:
    cases: list[CacheBenchmarkCase] = []
    idx = 0

    def next_id() -> str:
        nonlocal idx
        idx += 1
        return f"cb-{idx:04d}"

    for role in sorted(ROLE_RESOURCE_ALLOWLIST):
        for resource_type in sorted(ROLE_RESOURCE_ALLOWLIST[role]):
            anchor_id = next_id()
            prompt, purpose = _anchor_prompt(role, resource_type)

            anchor_req = AccessRequest(
                request_id=anchor_id,
                timestamp_utc=_IN_HOURS_TS,
                user=_user(anchor_id, role),
                context=_context(anchor_id),
                resource=_resource(anchor_id, resource_type),
                query=QueryInfo(prompt=prompt, purpose=purpose),
            )
            cases.append(CacheBenchmarkCase(
                case_id=anchor_id,
                phase="anchor",
                anchor_id=None,
                variant_type=None,
                expected_decision="ALLOW",
                expected_reason_code="POLICY_PASS",
                note=f"anchor: {role}/{resource_type}/internal/normal",
                request=anchor_req.model_dump(mode="json"),
            ))

            # ── paraphrase variant ────────────────────────────────────────────
            para_id = next_id()
            para_prompt, para_purpose = _paraphrase_prompt(role, resource_type)
            para_req = AccessRequest(
                request_id=para_id,
                timestamp_utc=_IN_HOURS_TS,
                user=_user(para_id, role),
                context=_context(para_id),
                resource=_resource(para_id, resource_type),
                query=QueryInfo(prompt=para_prompt, purpose=para_purpose),
            )
            cases.append(CacheBenchmarkCase(
                case_id=para_id,
                phase="variant",
                anchor_id=anchor_id,
                variant_type="paraphrase",
                expected_decision="ALLOW",
                expected_reason_code="POLICY_PASS",
                note=f"paraphrase of {anchor_id}; different wording, same artifact; cache should hit correctly",
                request=para_req.model_dump(mode="json"),
            ))

            # ── artifact_swap variant ─────────────────────────────────────────
            swap_id = next_id()
            swap_prompt, swap_purpose = _artifact_swap_prompt(role, resource_type)
            swap_req = AccessRequest(
                request_id=swap_id,
                timestamp_utc=_IN_HOURS_TS,
                user=_user(swap_id, role),
                context=_context(swap_id),
                resource=_resource(swap_id, resource_type),
                query=QueryInfo(prompt=swap_prompt, purpose=swap_purpose),
            )
            cases.append(CacheBenchmarkCase(
                case_id=swap_id,
                phase="variant",
                anchor_id=anchor_id,
                variant_type="artifact_swap",
                expected_decision="ALLOW",
                expected_reason_code="POLICY_PASS",
                note=f"artifact_swap of {anchor_id}; same template, different artifact; tests threshold boundary",
                request=swap_req.model_dump(mode="json"),
            ))

            # ── near_miss_incident variant ────────────────────────────────────
            nm_inc_id = next_id()
            nm_inc_req = AccessRequest(
                request_id=nm_inc_id,
                timestamp_utc=_IN_HOURS_TS,
                user=_user(nm_inc_id, role),
                context=_context(nm_inc_id, incident_state=IncidentState.critical),
                resource=_resource(nm_inc_id, resource_type),
                query=QueryInfo(prompt=prompt, purpose=purpose),
            )
            cases.append(CacheBenchmarkCase(
                case_id=nm_inc_id,
                phase="variant",
                anchor_id=anchor_id,
                variant_type="near_miss_incident",
                expected_decision="ESCALATE_HUMAN",
                expected_reason_code="INCIDENT_CRITICAL",
                note=(
                    f"near_miss of {anchor_id}; identical prompt, critical incident; "
                    "soft policy re-evaluated on cache hit — expects ESCALATE_HUMAN from LLM fallthrough"
                ),
                request=nm_inc_req.model_dump(mode="json"),
            ))

            # ── near_miss_elevated_confidential (HIGH_CLEARANCE_ROLES only) ───
            if role in HIGH_CLEARANCE_ROLES:
                nm_elev_id = next_id()
                nm_elev_req = AccessRequest(
                    request_id=nm_elev_id,
                    timestamp_utc=_IN_HOURS_TS,
                    user=UserInfo(
                        user_id=f"user-{role}-{nm_elev_id}",
                        role=role,
                        department=ROLE_DEPARTMENTS.get(role, "external"),
                        region="us",
                        clearance_level=3,  # same as anchor for high-clearance roles
                    ),
                    context=_context(nm_elev_id, incident_state=IncidentState.elevated),
                    resource=ResourceInfo(
                        resource_type=resource_type,
                        resource_id=f"{resource_type}-{nm_elev_id}",
                        sensitivity=Sensitivity.confidential,
                    ),
                    query=QueryInfo(prompt=prompt, purpose=purpose),
                )
                cases.append(CacheBenchmarkCase(
                    case_id=nm_elev_id,
                    phase="variant",
                    anchor_id=anchor_id,
                    variant_type="near_miss_elevated_conf",
                    expected_decision="ESCALATE_HUMAN",
                    expected_reason_code="INCIDENT_ELEVATED_RESTRICTED_FAST_PATH",
                    note=(
                        f"near_miss of {anchor_id}; identical prompt, elevated+confidential; "
                        "soft policy re-evaluated on cache hit — expects ESCALATE_HUMAN from LLM fallthrough"
                    ),
                    request=nm_elev_req.model_dump(mode="json"),
                ))

    return cases


def build_summary(cases: list[CacheBenchmarkCase]) -> dict:
    anchors = [c for c in cases if c.phase == "anchor"]
    variants = [c for c in cases if c.phase == "variant"]
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_cases": len(cases),
        "anchor_count": len(anchors),
        "variant_count": len(variants),
        "variant_type_counts": dict(Counter(c.variant_type for c in variants)),
        "expected_decision_counts": dict(Counter(c.expected_decision for c in cases)),
        "safety_note": (
            "_handle_cache_hit() re-evaluates evaluate_soft(req) before returning ALLOW_CACHE. "
            "near_miss variants verify this protection: 0% false-allow rate is the correct result. "
            "A non-zero rate indicates a regression in the soft-policy re-evaluation path."
        ),
    }


def main() -> None:
    cases = build_cases()
    DEFAULT_DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DEFAULT_DATASET_PATH.open("w", encoding="utf-8", newline="\n") as fh:
        for case in cases:
            fh.write(json.dumps(asdict(case), ensure_ascii=True) + "\n")
    summary = build_summary(cases)
    DEFAULT_SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
