from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # noqa: BLE001
    SentenceTransformer = None

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingService:
    model_id: str
    device: str = "cpu"
    cache_dir: str | None = None
    local_files_only: bool = False
    normalize: bool = True
    expected_dim: int = 384
    _model: Any = None
    _startup_error: str = ""

    def __post_init__(self) -> None:
        self._load_model()

    def encode(self, text: str) -> list[float]:
        if self._model is None:
            raise RuntimeError(self._startup_error or "embedding model unavailable")
        if not text:
            return [0.0] * self.expected_dim

        kwargs = {
            "normalize_embeddings": self.normalize,
            "convert_to_numpy": True,
        }
        if hasattr(self._model, "encode_query"):
            vector = self._model.encode_query(text, **kwargs)
        else:
            vector = self._model.encode(text, **kwargs)
        if hasattr(vector, "tolist"):
            vector = vector.tolist()
        if vector and isinstance(vector[0], list):
            vector = vector[0]
        return [float(value) for value in vector]

    def ping(self) -> tuple[bool, str]:
        if self._model is None:
            return False, self._startup_error or "embedding model unavailable"
        return True, (
            f"loaded model={self.model_id} device={self.device} "
            f"local_files_only={self.local_files_only}"
        )

    def _load_model(self) -> None:
        if self._model is not None:
            return
        if SentenceTransformer is None:
            self._startup_error = "sentence-transformers unavailable"
            return

        kwargs: dict[str, Any] = {
            "device": self.device,
            "local_files_only": self.local_files_only,
        }
        if self.cache_dir:
            kwargs["cache_folder"] = self.cache_dir
        try:
            self._model = SentenceTransformer(self.model_id, **kwargs)
            try:
                dim = int(self._model.get_sentence_embedding_dimension())
            except Exception:  # noqa: BLE001
                dim = 0
            if dim:
                self.expected_dim = dim
            logger.info(
                "Loaded embedding model model_id=%s device=%s local_files_only=%s",
                self.model_id,
                self.device,
                self.local_files_only,
            )
        except Exception as exc:  # noqa: BLE001
            self._startup_error = str(exc)
            logger.warning(
                "Failed to load embedding model model_id=%s device=%s local_files_only=%s error=%s",
                self.model_id,
                self.device,
                self.local_files_only,
                exc,
            )
