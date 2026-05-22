from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="dev", alias="APP_ENV")
    app_policy_version: str = Field(default="2026-04-04", alias="APP_POLICY_VERSION")

    opa_url: str = Field(default="http://localhost:8181", alias="OPA_URL")
    opa_enabled: bool = Field(default=False, alias="OPA_ENABLED")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    vllm_base_url: str = Field(default="http://localhost:8001/v1", alias="VLLM_BASE_URL")
    llm_input_cost_per_1m_tokens: float = Field(default=0.15, alias="LLM_INPUT_COST_PER_1M_TOKENS")
    llm_output_cost_per_1m_tokens: float = Field(default=0.60, alias="LLM_OUTPUT_COST_PER_1M_TOKENS")
    embedding_model_id: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        alias="EMBEDDING_MODEL_ID",
    )
    validation_model_id: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        alias="VALIDATION_MODEL_ID",
    )
    model_device: str = Field(default="cpu", alias="MODEL_DEVICE")
    model_cache_dir: str = Field(default="", alias="MODEL_CACHE_DIR")
    model_local_files_only: bool = Field(default=False, alias="MODEL_LOCAL_FILES_ONLY")
    embedding_normalize: bool = Field(default=True, alias="EMBEDDING_NORMALIZE")
    validation_threshold: float = Field(default=0.80, alias="VALIDATION_THRESHOLD")
    shadow_llm_provider: str = Field(default="", alias="SHADOW_LLM_PROVIDER")
    shadow_sampling_rate: float = Field(default=0.1, alias="SHADOW_SAMPLING_RATE")

    qdrant_url: str = Field(default="http://localhost:6333", alias="QDRANT_URL")
    qdrant_api_key: str = Field(default="", alias="QDRANT_API_KEY")
    qdrant_enabled: bool = Field(default=False, alias="QDRANT_ENABLED")
    qdrant_semantic_collection: str = Field(default="acl_semantic_cache_v2", alias="QDRANT_SEMANTIC_COLLECTION")
    qdrant_attack_collection: str = Field(default="acl_attack_patterns_v2", alias="QDRANT_ATTACK_COLLECTION")
    qdrant_vector_size: int = Field(default=384, alias="QDRANT_VECTOR_SIZE")

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    redis_enabled: bool = Field(default=False, alias="REDIS_ENABLED")

    kafka_bootstrap_servers: str = Field(default="localhost:9092", alias="KAFKA_BOOTSTRAP_SERVERS")
    kafka_enabled: bool = Field(default=False, alias="KAFKA_ENABLED")

    object_store_bucket: str = Field(default="acl-audit", alias="OBJECT_STORE_BUCKET")
    object_store_enabled: bool = Field(default=False, alias="OBJECT_STORE_ENABLED")


@lru_cache
def get_settings() -> Settings:
    return Settings()
