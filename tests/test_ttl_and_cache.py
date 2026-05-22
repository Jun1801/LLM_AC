from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.clients.ticket_client import TicketStoreClient
from app.clients.vector_client import VectorStoreClient
from app.models import Sensitivity
from app.ttl import compute_dynamic_ttl


def test_dynamic_ttl_bounds(sample_request):
    sample_request.resource.sensitivity = Sensitivity.confidential
    ttl = compute_dynamic_ttl(sample_request, confidence=0.95)
    assert ttl >= 300
    assert ttl <= 7200


def test_policy_version_invalidation(sample_request):
    vector = VectorStoreClient(enabled=False)
    emb = [0.1] * 16
    vector.upsert_cache_entry(
        item_id="x",
        embedding=emb,
        payload={
            "role": sample_request.user.role,
            "department": sample_request.user.department,
            "region": sample_request.user.region,
            "clearance_level": sample_request.user.clearance_level,
            "resource_type": sample_request.resource.resource_type,
            "policy_version": "old-policy",
            "cached_text": sample_request.query.prompt,
            "cached_decision": "ALLOW",
        },
    )
    result = vector.search_semantic_cache(
        embedding=emb,
        metadata_filters={
            "role": sample_request.user.role,
            "department": sample_request.user.department,
            "region": sample_request.user.region,
            "clearance_level": sample_request.user.clearance_level,
            "resource_type": sample_request.resource.resource_type,
        },
        policy_version="new-policy",
    )
    assert not result.hit


def test_expired_cache_entry_is_ignored(sample_request):
    vector = VectorStoreClient(enabled=False)
    emb = [0.1] * 16
    vector.upsert_cache_entry(
        item_id="expired",
        embedding=emb,
        payload={
            "role": sample_request.user.role,
            "department": sample_request.user.department,
            "region": sample_request.user.region,
            "clearance_level": sample_request.user.clearance_level,
            "resource_type": sample_request.resource.resource_type,
            "policy_version": "2026-04-04",
            "cached_text": sample_request.query.prompt,
            "cached_decision": "ALLOW",
            "expires_at_ts": int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp()),
        },
    )
    result = vector.search_semantic_cache(
        embedding=emb,
        metadata_filters={
            "role": sample_request.user.role,
            "department": sample_request.user.department,
            "region": sample_request.user.region,
            "clearance_level": sample_request.user.clearance_level,
            "resource_type": sample_request.resource.resource_type,
        },
        policy_version="2026-04-04",
    )
    assert not result.hit


def test_ticket_store_local_fallback_expires():
    store = TicketStoreClient(enabled=False)
    store.issue_ticket("u-1", "r-1", ttl_seconds=1)
    assert store.has_ticket("u-1", "r-1")
    store._tickets[store._key("u-1", "r-1")] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert not store.has_ticket("u-1", "r-1")
