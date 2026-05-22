from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.dependencies import get_vector_client
from app.models import CacheUpdateMessage, Decision
from app.ttl import compute_dynamic_ttl
from workers.common import drain_topic


def run_once() -> int:
    vector = get_vector_client()
    messages = drain_topic("cache.update")
    processed = 0
    for msg in messages:
        payload = msg["payload"]
        update = CacheUpdateMessage.model_validate(payload)
        if update.response.decision == Decision.ESCALATE_HUMAN:
            continue
        ttl = compute_dynamic_ttl(update.request, update.response.confidence, policy_stability_factor=1.0)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        item_id = f"{update.request.user.user_id}:{update.request.resource.resource_id}:{update.request.request_id}"
        vector.upsert_cache_entry(
            item_id=item_id,
            embedding=update.embedding,
            payload={
                "role": update.request.user.role,
                "department": update.request.user.department,
                "region": update.request.user.region,
                "clearance_level": update.request.user.clearance_level,
                "resource_type": update.request.resource.resource_type,
                "policy_version": update.response.policy_version,
                "cached_text": update.request.query.prompt,
                "cached_decision": update.response.decision,
                "ttl_seconds": ttl,
                "expires_at_ts": int(expires_at.timestamp()),
                "expires_at_utc": expires_at.isoformat(),
            },
        )
        processed += 1
    return processed


if __name__ == "__main__":
    count = run_once()
    print(f"cache_update processed={count}")
