from __future__ import annotations

from app.dependencies import get_event_bus


def drain_topic(topic: str) -> list[dict]:
    bus = get_event_bus()
    selected = [x for x in bus.published if x["topic"] == topic]
    bus.published = [x for x in bus.published if x["topic"] != topic]
    return selected

