from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EventBusClient:
    enabled: bool = False
    published: list[dict[str, Any]] = field(default_factory=list)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        self.published.append({"topic": topic, "payload": payload})

    def ping(self) -> tuple[bool, str]:
        if not self.enabled:
            return True, "disabled (local fallback)"
        return True, "enabled (placeholder client)"

