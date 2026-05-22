from __future__ import annotations

from app.models import AccessRequest


ROLE_BASE_TTL = {
    "admin": 1800,
    "analyst": 7200,
    "nurse": 3600,
}


def sensitivity_max_ttl(sensitivity: str) -> int:
    if sensitivity in {"restricted", "confidential"}:
        return 7200
    return 86400


def compute_dynamic_ttl(req: AccessRequest, confidence: float, policy_stability_factor: float = 1.0) -> int:
    base = ROLE_BASE_TTL.get(req.user.role.lower(), 3600)
    confidence_factor = max(0.5, min(1.2, confidence))
    ttl = int(base * confidence_factor * policy_stability_factor)
    ttl = max(300, ttl)
    ttl = min(ttl, sensitivity_max_ttl(req.resource.sensitivity.value))
    return ttl

