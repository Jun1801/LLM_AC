from __future__ import annotations

from app.dependencies import get_embedding_service, get_vector_client
from workers.common import drain_topic


def run_once() -> int:
    embedding = get_embedding_service()
    vector = get_vector_client()
    messages = drain_topic("feedback.events")
    processed = 0
    for msg in messages:
        payload = msg["payload"]
        if not payload.get("suspicious", False):
            continue
        prompt = payload.get("prompt", "")
        emb = embedding.encode(prompt)
        vector.upsert_attack_pattern(
            item_id=f"feedback-{payload.get('request_id', 'unknown')}",
            embedding=emb,
            payload={"source": "feedback", "reason_code": payload.get("reason_code", ""), "prompt": prompt},
        )
        processed += 1
    return processed


if __name__ == "__main__":
    count = run_once()
    print(f"feedback_worker processed={count}")
