from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.dependencies import get_kpi_tracker, get_mode_manager, get_pipeline
from app.models import Mode, ModeOverrideRequest, ModeOverrideResponse

_VALID_ABLATION_MODES = {"none", "no_cache_reeval", "no_cache", "llm_only"}


class AblationRequest(BaseModel):
    mode: str

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.post("/mode", response_model=ModeOverrideResponse)
def set_mode_override(payload: ModeOverrideRequest) -> ModeOverrideResponse:
    manager = get_mode_manager()
    expires = manager.set_override(payload.mode, payload.ttl_seconds)
    return ModeOverrideResponse(mode=payload.mode, expires_at_utc=expires)


@router.get("/kpi")
def get_kpi_snapshot() -> dict:
    s = get_kpi_tracker().snapshot()
    return {
        "total": s.total,
        "cache_hits": s.cache_hits,
        "cache_hit_ratio": s.cache_hit_ratio,
        "escalations": s.escalations,
        "escalation_rate": s.escalation_rate,
        "threat_denies": s.threat_denies,
        "threat_deny_rate": s.threat_deny_rate,
        "avg_latency_ms": s.avg_latency_ms,
    }


@router.post("/ablation")
def set_ablation_mode(payload: AblationRequest) -> dict:
    if payload.mode not in _VALID_ABLATION_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid ablation mode. Valid: {sorted(_VALID_ABLATION_MODES)}")
    get_pipeline().ablation_mode = payload.mode
    return {"ablation_mode": payload.mode}


@router.get("/ablation")
def get_ablation_mode() -> dict:
    return {"ablation_mode": get_pipeline().ablation_mode}


@router.post("/mode/auto-check")
def auto_mode_check() -> dict:
    manager = get_mode_manager()
    kpi = get_kpi_tracker().snapshot()
    triggered = kpi.escalation_rate > 0.08 or kpi.threat_deny_rate > 0.2
    if triggered:
        expires = manager.set_override(Mode.conservative, 900)
        return {"triggered": True, "mode": "conservative", "expires_at_utc": expires}
    return {"triggered": False, "mode": manager.get_mode()}
