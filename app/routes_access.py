from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import get_pipeline
from app.models import AccessRequest, AccessResponse

router = APIRouter(prefix="/v1/access", tags=["access"])


@router.post("/decide", response_model=AccessResponse)
def decide_access(payload: AccessRequest) -> AccessResponse:
    return get_pipeline().decide(payload)

