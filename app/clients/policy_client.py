from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone

import httpx

from app.models import AccessRequest, Decision, PolicyResult, Sensitivity


SENSITIVITY_MIN_CLEARANCE: dict[Sensitivity, int] = {
    Sensitivity.public: 0,
    Sensitivity.internal: 1,
    Sensitivity.restricted: 2,
    Sensitivity.confidential: 3,
}

ROLE_RESOURCE_ALLOWLIST: dict[str, set[str]] = {
    "analyst": {"document", "report", "dashboard"},
    "manager": {"document", "report", "dashboard", "ticket"},
    "auditor": {"document", "report", "dataset", "dashboard"},
    "engineer": {"document", "dashboard", "dataset"},
    "security_analyst": {"document", "dataset", "dashboard", "ticket"},
    "hr_partner": {"document", "report", "dataset"},
    "legal_counsel": {"document", "dataset", "ticket"},
}

HIGH_RISK_WINDOW_START_HOUR_UTC = 2
HIGH_RISK_WINDOW_END_HOUR_UTC = 6


@dataclass
class OPAClient:
    base_url: str
    enabled: bool = False
    timeout_seconds: float = 2.0

    def _post(self, path: str, payload: dict) -> dict:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(f"{self.base_url}{path}", json={"input": payload})
            response.raise_for_status()
            return response.json().get("result", {})

    def evaluate_hard(self, req: AccessRequest) -> PolicyResult:
        if self.enabled:
            result = self._post("/v1/data/access/hard_allow", req.model_dump(mode="json"))
            allow = bool(result.get("allow", False))
            return PolicyResult(
                allow=allow,
                reason_code=result.get("reason_code", "HARD_POLICY_EVALUATED"),
                matched_rule=result.get("matched_rule"),
            )
        return self._evaluate_hard_fallback(req)

    def evaluate_soft(self, req: AccessRequest) -> PolicyResult:
        if self.enabled:
            result = self._post("/v1/data/access/soft_allow", req.model_dump(mode="json"))
            allow = bool(result.get("allow", False))
            return PolicyResult(
                allow=allow,
                reason_code=result.get("reason_code", "SOFT_POLICY_EVALUATED"),
                matched_rule=result.get("matched_rule"),
            )
        return self._evaluate_soft_fallback(req)

    def veto(self, req: AccessRequest, proposed: Decision) -> tuple[Decision, str]:
        hard = self.evaluate_hard(req)
        if not hard.allow:
            return Decision.DENY, f"VETO_{hard.reason_code}"
        if proposed in {Decision.ALLOW_CACHE, Decision.ALLOW_EMERGENCY}:
            return Decision.ALLOW, "VETO_NORMALIZED_ALLOW"
        return proposed, "VETO_PASS"

    def ping(self) -> tuple[bool, str]:
        if not self.enabled:
            return True, "disabled (local fallback)"
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.get(f"{self.base_url}/health")
                return resp.status_code < 500, f"status={resp.status_code}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    def _evaluate_hard_fallback(self, req: AccessRequest) -> PolicyResult:
        if req.context.mfa_state != "passed":
            return PolicyResult(allow=False, reason_code="MFA_REQUIRED", matched_rule="mfa_required")
        if not req.context.session_id:
            return PolicyResult(allow=False, reason_code="SESSION_INVALID", matched_rule="session_required")
        if req.user.clearance_level < SENSITIVITY_MIN_CLEARANCE[req.resource.sensitivity]:
            return PolicyResult(allow=False, reason_code="CLEARANCE_TOO_LOW", matched_rule="clearance_guard")
        allowed_resource_types = ROLE_RESOURCE_ALLOWLIST.get(req.user.role, set())
        if req.resource.resource_type not in allowed_resource_types:
            return PolicyResult(allow=False, reason_code="ROLE_RESOURCE_DENIED", matched_rule="role_resource_guard")
        return PolicyResult(allow=True, reason_code="HARD_POLICY_PASS", matched_rule="default_allow")

    def _evaluate_soft_fallback(self, req: AccessRequest) -> PolicyResult:
        if req.context.incident_state.value == "critical":
            return PolicyResult(allow=False, reason_code="INCIDENT_CRITICAL", matched_rule="incident_guard")
        if req.context.incident_state.value == "elevated" and req.resource.sensitivity == Sensitivity.confidential:
            return PolicyResult(
                allow=False,
                reason_code="INCIDENT_ELEVATED_RESTRICTED_FAST_PATH",
                matched_rule="incident_elevated_confidential_guard",
            )
        access_hour_utc = req.timestamp_utc.astimezone(timezone.utc).hour
        if HIGH_RISK_WINDOW_START_HOUR_UTC <= access_hour_utc < HIGH_RISK_WINDOW_END_HOUR_UTC:
            return PolicyResult(
                allow=False,
                reason_code="OUT_OF_HOURS_FAST_PATH_REVIEW",
                matched_rule="time_window_guard",
            )
        return PolicyResult(allow=True, reason_code="SOFT_POLICY_PASS", matched_rule="default_allow")
