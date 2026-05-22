from __future__ import annotations

from datetime import datetime, timezone

from app.dependencies import get_object_store
from workers.common import drain_topic


def run_once() -> int:
    store = get_object_store()
    messages = drain_topic("audit.events")
    processed = 0
    for msg in messages:
        payload = msg["payload"]
        req_id = payload.get("request_id", "unknown")
        key = f"audit/{datetime.now(timezone.utc).date().isoformat()}/{req_id}.json"
        store.put_json(key, payload)
        processed += 1
    return processed


if __name__ == "__main__":
    count = run_once()
    print(f"audit_worker processed={count}")

