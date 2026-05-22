from __future__ import annotations

from dataclasses import dataclass
import logging
from math import exp
from typing import Any

from app.models import ValidationResult

try:
    from sentence_transformers.cross_encoder import CrossEncoder
except Exception:  # noqa: BLE001
    CrossEncoder = None

logger = logging.getLogger(__name__)


@dataclass
class ValidationService:
    model_id: str
    device: str = "cpu"
    cache_dir: str | None = None
    local_files_only: bool = False
    threshold: float = 0.80
    _model: Any = None
    _startup_error: str = ""

    def __post_init__(self) -> None:
        self._load_model()

    def validate(self, query_text: str, cached_text: str) -> ValidationResult:
        if self._model is None or not query_text or not cached_text:
            return ValidationResult(is_hit=False, score=0.0)
        raw_score = self._model.predict([(query_text, cached_text)])
        if hasattr(raw_score, "tolist"):
            raw_score = raw_score.tolist()
        if isinstance(raw_score, list):
            raw_score = raw_score[0]
        score = 1.0 / (1.0 + exp(-float(raw_score)))
        return ValidationResult(is_hit=score >= self.threshold, score=score)

    def ping(self) -> tuple[bool, str]:
        if self._model is None:
            return False, self._startup_error or "validation model unavailable"
        return True, (
            f"loaded model={self.model_id} device={self.device} "
            f"local_files_only={self.local_files_only}"
        )

    def _load_model(self) -> None:
        if self._model is not None:
            return
        if CrossEncoder is None:
            self._startup_error = "sentence-transformers cross-encoder unavailable"
            return

        kwargs: dict[str, Any] = {
            "device": self.device,
            "local_files_only": self.local_files_only,
        }
        if self.cache_dir:
            kwargs["cache_folder"] = self.cache_dir
        try:
            self._model = CrossEncoder(self.model_id, **kwargs)
            logger.info(
                "Loaded validation model model_id=%s device=%s local_files_only=%s",
                self.model_id,
                self.device,
                self.local_files_only,
            )
        except Exception as exc:  # noqa: BLE001
            self._startup_error = str(exc)
            logger.warning(
                "Failed to load validation model model_id=%s device=%s local_files_only=%s error=%s",
                self.model_id,
                self.device,
                self.local_files_only,
                exc,
            )
