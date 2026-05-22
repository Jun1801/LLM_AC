from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ObjectStoreClient:
    enabled: bool = False
    bucket: str = "acl-audit"
    objects: dict[str, dict[str, Any]] = field(default_factory=dict)

    def put_json(self, key: str, payload: dict[str, Any]) -> None:
        self.objects[key] = payload

    def ping(self) -> tuple[bool, str]:
        if not self.enabled:
            return True, "disabled (local fallback)"
        return True, f"enabled bucket={self.bucket}"

