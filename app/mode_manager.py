from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.models import Mode


@dataclass(frozen=True)
class Thresholds:
    t_attack: float
    t_hit: float
    t_validate_low: float


# t_attack is calibrated from the attack/benign similarity distribution
# (benign max ≈ 0.47, adversarial mean ≈ 0.60) and is intentionally
# decoupled from t_hit, which governs semantic cache routing.
MODE_THRESHOLDS = {
    Mode.loose: Thresholds(t_attack=0.52, t_hit=0.80, t_validate_low=0.60),
    Mode.moderate: Thresholds(t_attack=0.50, t_hit=0.85, t_validate_low=0.65),
    Mode.performance: Thresholds(t_attack=0.50, t_hit=0.88, t_validate_low=0.68),
    Mode.balanced: Thresholds(t_attack=0.50, t_hit=0.90, t_validate_low=0.70),
    Mode.conservative: Thresholds(t_attack=0.48, t_hit=0.93, t_validate_low=0.75),
    Mode.strict: Thresholds(t_attack=0.48, t_hit=0.95, t_validate_low=0.80),
}


class ModeManager:
    def __init__(self, default_mode: Mode = Mode.balanced):
        self._default_mode = default_mode
        self._override_mode: Mode | None = None
        self._override_expires_at: datetime | None = None

    def get_mode(self) -> Mode:
        now = datetime.now(timezone.utc)
        if self._override_mode and self._override_expires_at and now <= self._override_expires_at:
            return self._override_mode
        self._override_mode = None
        self._override_expires_at = None
        return self._default_mode

    def set_override(self, mode: Mode, ttl_seconds: int) -> datetime:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        self._override_mode = mode
        self._override_expires_at = expires_at
        return expires_at

    def thresholds(self) -> Thresholds:
        return MODE_THRESHOLDS[self.get_mode()]

