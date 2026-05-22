from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import sqrt
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.models import CacheCandidate

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
except Exception:  # noqa: BLE001
    QdrantClient = None
    qmodels = None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sqrt(sum(x * x for x in a))
    norm_b = sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass
class VectorItem:
    id: str
    vector: list[float]
    payload: dict[str, Any]


@dataclass
class VectorStoreClient:
    enabled: bool = False
    url: str = "http://localhost:6333"
    api_key: str = ""
    semantic_collection: str = "acl_semantic_cache_v2"
    attack_collection: str = "acl_attack_patterns_v2"
    vector_size: int = 384
    semantic_cache: list[VectorItem] = field(default_factory=list)
    attack_patterns: list[VectorItem] = field(default_factory=list)
    _client: Any = None
    _startup_error: str = ""

    def __post_init__(self) -> None:
        if not self.enabled or QdrantClient is None:
            return
        try:
            self._client = QdrantClient(
                url=self.url,
                api_key=self.api_key or None,
                check_compatibility=False,
            )
            self._ensure_collection(self.semantic_collection)
            self._ensure_collection(self.attack_collection)
        except Exception as exc:  # noqa: BLE001
            self._startup_error = str(exc)

    def search_attack_similarity(self, embedding: list[float]) -> tuple[float, str | None]:
        if self.enabled and self._client is not None:
            try:
                points = self._search_remote(self.attack_collection, embedding, limit=1, query_filter=None)
                if not points:
                    return 0.0, None
                point = points[0]
                return float(point.score), self._point_id(point)
            except Exception:  # noqa: BLE001
                return 0.0, None

        best_score = 0.0
        best_id = None
        for item in self.attack_patterns:
            score = cosine_similarity(embedding, item.vector)
            if score > best_score:
                best_score = score
                best_id = item.id
        return best_score, best_id

    def search_semantic_cache(
        self,
        embedding: list[float],
        metadata_filters: dict[str, Any],
        policy_version: str,
    ) -> CacheCandidate:
        if self.enabled and self._client is not None:
            try:
                query_filter = self._semantic_filter(metadata_filters, policy_version)
                points = self._search_remote(self.semantic_collection, embedding, limit=1, query_filter=query_filter)
                if not points:
                    return CacheCandidate(hit=False)
                point = points[0]
                payload = point.payload or {}
                return CacheCandidate(
                    hit=True,
                    similarity=float(point.score),
                    cached_text=payload.get("cached_text"),
                    cached_decision=payload.get("cached_decision"),
                    policy_version=payload.get("policy_version"),
                    metadata=payload,
                )
            except Exception:  # noqa: BLE001
                return CacheCandidate(hit=False)

        now_ts = int(datetime.now(timezone.utc).timestamp())
        best_item = None
        best_score = 0.0
        for item in self.semantic_cache:
            if not self._match_filters(item.payload, metadata_filters):
                continue
            if item.payload.get("policy_version") != policy_version:
                continue
            expires_at_ts = int(item.payload.get("expires_at_ts", 0) or 0)
            if expires_at_ts and expires_at_ts < now_ts:
                continue
            score = cosine_similarity(embedding, item.vector)
            if score > best_score:
                best_score = score
                best_item = item
        if not best_item:
            return CacheCandidate(hit=False)
        return CacheCandidate(
            hit=True,
            similarity=best_score,
            cached_text=best_item.payload.get("cached_text"),
            cached_decision=best_item.payload.get("cached_decision"),
            policy_version=best_item.payload.get("policy_version"),
            metadata=best_item.payload,
        )

    def upsert_cache_entry(self, item_id: str, embedding: list[float], payload: dict[str, Any]) -> None:
        if self.enabled and self._client is not None:
            try:
                self._client.upsert(
                    collection_name=self.semantic_collection,
                    points=[
                        qmodels.PointStruct(
                            id=self._normalize_point_id(item_id),
                            vector=embedding,
                            payload=payload,
                        )
                    ],
                )
                return
            except Exception:  # noqa: BLE001
                return

        for i, existing in enumerate(self.semantic_cache):
            if existing.id == item_id:
                self.semantic_cache[i] = VectorItem(id=item_id, vector=embedding, payload=payload)
                return
        self.semantic_cache.append(VectorItem(id=item_id, vector=embedding, payload=payload))

    def upsert_attack_pattern(self, item_id: str, embedding: list[float], payload: dict[str, Any]) -> None:
        if self.enabled and self._client is not None:
            try:
                self._client.upsert(
                    collection_name=self.attack_collection,
                    points=[
                        qmodels.PointStruct(
                            id=self._normalize_point_id(item_id or str(uuid4())),
                            vector=embedding,
                            payload=payload,
                        )
                    ],
                )
                return
            except Exception:  # noqa: BLE001
                return
        self.attack_patterns.append(VectorItem(id=item_id or str(uuid4()), vector=embedding, payload=payload))

    def ping(self) -> tuple[bool, str]:
        if not self.enabled:
            return True, "disabled (local fallback)"
        if self._client is None:
            return False, self._startup_error or "qdrant client unavailable"
        try:
            self._client.get_collections()
            return True, f"connected url={self.url}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    def _ensure_collection(self, name: str) -> None:
        if self._client is None or qmodels is None:
            return
        if self._client.collection_exists(name):
            existing_size = self._collection_vector_size(name)
            if existing_size and existing_size != self.vector_size:
                raise ValueError(
                    f"collection '{name}' vector size mismatch: expected {self.vector_size}, found {existing_size}"
                )
            return
        self._client.create_collection(
            collection_name=name,
            vectors_config=qmodels.VectorParams(size=self.vector_size, distance=qmodels.Distance.COSINE),
        )

    def _search_remote(self, collection_name: str, embedding: list[float], limit: int, query_filter: Any) -> list[Any]:
        if self._client is None:
            return []
        if hasattr(self._client, "query_points"):
            result = self._client.query_points(
                collection_name=collection_name,
                query=embedding,
                limit=limit,
                query_filter=query_filter,
                with_payload=True,
            )
            return list(getattr(result, "points", []))
        return list(
            self._client.search(
                collection_name=collection_name,
                query_vector=embedding,
                limit=limit,
                query_filter=query_filter,
                with_payload=True,
            )
        )

    def _semantic_filter(self, metadata_filters: dict[str, Any], policy_version: str) -> Any:
        if qmodels is None:
            return None
        now_ts = int(datetime.now(timezone.utc).timestamp())
        conditions = [
            qmodels.FieldCondition(key="policy_version", match=qmodels.MatchValue(value=policy_version)),
            qmodels.FieldCondition(key="expires_at_ts", range=qmodels.Range(gte=now_ts)),
        ]
        for key, expected in metadata_filters.items():
            conditions.append(qmodels.FieldCondition(key=key, match=qmodels.MatchValue(value=expected)))
        return qmodels.Filter(must=conditions)

    def _match_filters(self, payload: dict[str, Any], metadata_filters: dict[str, Any]) -> bool:
        for key, expected in metadata_filters.items():
            if payload.get(key) != expected:
                return False
        return True

    def _point_id(self, point: Any) -> str | None:
        point_id = getattr(point, "id", None)
        return str(point_id) if point_id is not None else None

    def _normalize_point_id(self, item_id: str) -> str:
        try:
            return str(uuid5(NAMESPACE_URL, item_id))
        except Exception:  # noqa: BLE001
            return str(uuid4())

    def _collection_vector_size(self, name: str) -> int:
        if self._client is None:
            return 0
        try:
            info = self._client.get_collection(name)
            params = getattr(getattr(info, "config", None), "params", None)
            vectors = getattr(params, "vectors", None)
            if hasattr(vectors, "size"):
                return int(vectors.size)
            if isinstance(vectors, dict):
                first = next(iter(vectors.values()), None)
                if hasattr(first, "size"):
                    return int(first.size)
            return 0
        except Exception:  # noqa: BLE001
            return 0
