from __future__ import annotations

from dataclasses import dataclass

from app.clients.vector_client import VectorStoreClient
from app.models import ThreatResult


@dataclass
class ThreatScreenService:
    vector_store: VectorStoreClient

    def evaluate(self, embedding: list[float]) -> ThreatResult:
        similarity, pattern_id = self.vector_store.search_attack_similarity(embedding)
        return ThreatResult(similarity=similarity, matched_pattern_id=pattern_id)

