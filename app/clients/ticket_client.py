from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

try:
    import redis
except Exception:  # noqa: BLE001
    redis = None


@dataclass
class TicketStoreClient:
    enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"
    _tickets: dict[str, datetime] = field(default_factory=dict)
    _client: object | None = None

    def __post_init__(self) -> None:
        if self.enabled and redis is not None:
            self._client = redis.from_url(self.redis_url, decode_responses=True)

    def _key(self, user_id: str, resource_id: str) -> str:
        return f"ticket:{user_id}:{resource_id}"

    def has_ticket(self, user_id: str, resource_id: str) -> bool:
        key = self._key(user_id, resource_id)
        if self.enabled and self._client is not None:
            try:
                return bool(self._client.exists(key))
            except Exception:  # noqa: BLE001
                return False

        exp = self._tickets.get(key)
        if not exp:
            return False
        if datetime.now(timezone.utc) > exp:
            self._tickets.pop(key, None)
            return False
        return True

    def issue_ticket(self, user_id: str, resource_id: str, ttl_seconds: int = 900) -> None:
        key = self._key(user_id, resource_id)
        if self.enabled and self._client is not None:
            try:
                self._client.setex(key, ttl_seconds, "1")
                return
            except Exception:  # noqa: BLE001
                return
        self._tickets[key] = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

    def ping(self) -> tuple[bool, str]:
        if not self.enabled:
            return True, "disabled (local fallback)"
        if self._client is None:
            return False, "redis client unavailable"
        try:
            ok = self._client.ping()
            return bool(ok), f"connected url={self.redis_url}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

