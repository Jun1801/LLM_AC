from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.dependencies import (
    get_embedding_service,
    get_event_bus,
    get_kpi_tracker,
    get_llm_provider,
    get_mode_manager,
    get_object_store,
    get_policy_client,
    get_shadow_llm_provider,
    get_ticket_store,
    get_validation_service,
    get_vector_client,
)
from app.models import AccessRequest, ContextInfo, QueryInfo, ResourceInfo, Sensitivity, UserInfo


@pytest.fixture(autouse=True)
def reset_singletons():
    get_mode_manager.cache_clear()
    get_policy_client.cache_clear()
    get_vector_client.cache_clear()
    get_ticket_store.cache_clear()
    get_event_bus.cache_clear()
    get_object_store.cache_clear()
    get_llm_provider.cache_clear()
    get_shadow_llm_provider.cache_clear()
    get_kpi_tracker.cache_clear()
    get_embedding_service.cache_clear()
    get_validation_service.cache_clear()
    yield


@pytest.fixture
def sample_request() -> AccessRequest:
    return AccessRequest(
        request_id="req-1",
        timestamp_utc=datetime.now(timezone.utc),
        user=UserInfo(
            user_id="u-1",
            role="analyst",
            department="finance",
            region="us",
            clearance_level=2,
        ),
        context=ContextInfo(
            ip_address="10.1.1.1",
            device_id="dev-1",
            session_id="sess-1",
            mfa_state="passed",
            incident_state="normal",
        ),
        resource=ResourceInfo(
            resource_type="document",
            resource_id="doc-1",
            sensitivity=Sensitivity.internal,
        ),
        query=QueryInfo(prompt="Need access to report 2026", purpose="monthly close"),
    )
