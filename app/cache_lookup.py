from __future__ import annotations

from dataclasses import dataclass

from app.clients.vector_client import VectorStoreClient
from app.models import AccessRequest, CacheCandidate


@dataclass
class CacheLookupService:
    vector_store: VectorStoreClient

    def lookup(self, req: AccessRequest, embedding: list[float], policy_version: str) -> CacheCandidate:
        filters = {
            "role": req.user.role,
            "department": req.user.department,
            "region": req.user.region,
            "clearance_level": req.user.clearance_level,
            "resource_type": req.resource.resource_type,
        }
        return self.vector_store.search_semantic_cache(
            embedding=embedding,
            metadata_filters=filters,
            policy_version=policy_version,
        )

