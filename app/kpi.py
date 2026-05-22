from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from app.models import AccessResponse, Decision


@dataclass
class KPISnapshot:
    total: int
    cache_hits: int
    escalations: int
    threat_denies: int
    avg_latency_ms: float

    @property
    def cache_hit_ratio(self) -> float:
        return 0.0 if self.total == 0 else self.cache_hits / self.total

    @property
    def escalation_rate(self) -> float:
        return 0.0 if self.total == 0 else self.escalations / self.total

    @property
    def threat_deny_rate(self) -> float:
        return 0.0 if self.total == 0 else self.threat_denies / self.total


class KPITracker:
    def __init__(self) -> None:
        self._lock = Lock()
        self._total = 0
        self._cache_hits = 0
        self._escalations = 0
        self._threat_denies = 0
        self._latency_sum = 0

    def record(self, resp: AccessResponse) -> None:
        with self._lock:
            self._total += 1
            if resp.decision in {Decision.ALLOW_CACHE, Decision.ALLOW_EMERGENCY}:
                self._cache_hits += 1
            if resp.decision == Decision.ESCALATE_HUMAN:
                self._escalations += 1
            if resp.reason_code == "THREAT_PATTERN_MATCH":
                self._threat_denies += 1
            self._latency_sum += resp.latency_ms

    def snapshot(self) -> KPISnapshot:
        with self._lock:
            avg = 0.0 if self._total == 0 else self._latency_sum / self._total
            return KPISnapshot(
                total=self._total,
                cache_hits=self._cache_hits,
                escalations=self._escalations,
                threat_denies=self._threat_denies,
                avg_latency_ms=avg,
            )

