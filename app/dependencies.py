from __future__ import annotations

from functools import lru_cache

from app.cache_lookup import CacheLookupService
from app.clients.event_client import EventBusClient
from app.clients.llm_client import OpenAIDecisionProvider, VLLMDecisionProvider
from app.clients.object_store_client import ObjectStoreClient
from app.clients.policy_client import OPAClient
from app.clients.ticket_client import TicketStoreClient
from app.clients.vector_client import VectorStoreClient
from app.config import get_settings
from app.embedding import EmbeddingService
from app.ingestion import IngestionService
from app.kpi import KPITracker
from app.mode_manager import ModeManager
from app.pipeline import AccessPipeline
from app.threat_screen import ThreatScreenService
from app.validation import ValidationService


@lru_cache
def get_mode_manager() -> ModeManager:
    return ModeManager()


@lru_cache
def get_policy_client() -> OPAClient:
    s = get_settings()
    return OPAClient(base_url=s.opa_url, enabled=s.opa_enabled)


@lru_cache
def get_vector_client() -> VectorStoreClient:
    s = get_settings()
    return VectorStoreClient(
        enabled=s.qdrant_enabled,
        url=s.qdrant_url,
        api_key=s.qdrant_api_key,
        semantic_collection=s.qdrant_semantic_collection,
        attack_collection=s.qdrant_attack_collection,
        vector_size=s.qdrant_vector_size,
    )


@lru_cache
def get_embedding_service() -> EmbeddingService:
    s = get_settings()
    return EmbeddingService(
        model_id=s.embedding_model_id,
        device=s.model_device,
        cache_dir=s.model_cache_dir or None,
        local_files_only=s.model_local_files_only,
        normalize=s.embedding_normalize,
        expected_dim=s.qdrant_vector_size,
    )


@lru_cache
def get_validation_service() -> ValidationService:
    s = get_settings()
    return ValidationService(
        model_id=s.validation_model_id,
        device=s.model_device,
        cache_dir=s.model_cache_dir or None,
        local_files_only=s.model_local_files_only,
        threshold=s.validation_threshold,
    )


@lru_cache
def get_ticket_store() -> TicketStoreClient:
    s = get_settings()
    return TicketStoreClient(enabled=s.redis_enabled, redis_url=s.redis_url)


@lru_cache
def get_event_bus() -> EventBusClient:
    s = get_settings()
    return EventBusClient(enabled=s.kafka_enabled)


@lru_cache
def get_object_store() -> ObjectStoreClient:
    s = get_settings()
    return ObjectStoreClient(enabled=s.object_store_enabled, bucket=s.object_store_bucket)


@lru_cache
def get_llm_provider():
    s = get_settings()
    if s.llm_provider.lower() == "vllm":
        return VLLMDecisionProvider(
            base_url=s.vllm_base_url,
            input_cost_per_1m_tokens=s.llm_input_cost_per_1m_tokens,
            output_cost_per_1m_tokens=s.llm_output_cost_per_1m_tokens,
        )
    return OpenAIDecisionProvider(
        api_key=s.openai_api_key,
        model=s.openai_model,
        input_cost_per_1m_tokens=s.llm_input_cost_per_1m_tokens,
        output_cost_per_1m_tokens=s.llm_output_cost_per_1m_tokens,
    )


@lru_cache
def get_shadow_llm_provider():
    s = get_settings()
    provider = s.shadow_llm_provider.lower().strip()
    if not provider:
        return None
    if provider == "vllm":
        return VLLMDecisionProvider(
            base_url=s.vllm_base_url,
            input_cost_per_1m_tokens=s.llm_input_cost_per_1m_tokens,
            output_cost_per_1m_tokens=s.llm_output_cost_per_1m_tokens,
        )
    if provider == "openai":
        return OpenAIDecisionProvider(
            api_key=s.openai_api_key,
            model=s.openai_model,
            input_cost_per_1m_tokens=s.llm_input_cost_per_1m_tokens,
            output_cost_per_1m_tokens=s.llm_output_cost_per_1m_tokens,
        )
    return None


@lru_cache
def get_kpi_tracker() -> KPITracker:
    return KPITracker()


_pipeline: AccessPipeline | None = None


def get_pipeline() -> AccessPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = build_pipeline()
    return _pipeline


def build_pipeline() -> AccessPipeline:
    settings = get_settings()
    vector_client = get_vector_client()
    return AccessPipeline(
        policy_version=settings.app_policy_version,
        mode_manager=get_mode_manager(),
        ingestion=IngestionService(),
        policy=get_policy_client(),
        embedding=get_embedding_service(),
        threat_screen=ThreatScreenService(vector_store=vector_client),
        cache_lookup=CacheLookupService(vector_store=vector_client),
        validation=get_validation_service(),
        llm_provider=get_llm_provider(),
        shadow_llm_provider=get_shadow_llm_provider(),
        shadow_sampling_rate=settings.shadow_sampling_rate,
        ticket_store=get_ticket_store(),
        events=get_event_bus(),
        vector_store=vector_client,
        kpi_tracker=get_kpi_tracker(),
    )
