from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import (
    get_embedding_service,
    get_event_bus,
    get_llm_provider,
    get_object_store,
    get_policy_client,
    get_ticket_store,
    get_validation_service,
    get_vector_client,
)
from app.models import HealthResponse, ReadyDependency, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
def ready() -> ReadyResponse:
    checks = []
    for name, client in [
        ("policy", get_policy_client()),
        ("vector_store", get_vector_client()),
        ("ticket_store", get_ticket_store()),
        ("event_bus", get_event_bus()),
        ("object_store", get_object_store()),
        ("llm_provider", get_llm_provider()),
        ("embedding_service", get_embedding_service()),
        ("validation_service", get_validation_service()),
    ]:
        ok, msg = client.ping()
        checks.append(ReadyDependency(name=name, ok=ok, message=msg))
    status = "ready" if all(x.ok for x in checks) else "degraded"
    return ReadyResponse(status=status, dependencies=checks)
