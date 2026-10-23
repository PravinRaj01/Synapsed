from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server settings, read from the environment or backend/.env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database: the app role (RLS enforced) and the owner role (migrations/seed only).
    database_url: str = ""
    database_url_admin: str = ""

    # Neon Auth: base URL of the Managed Better Auth instance.
    neon_auth_base_url: str = ""

    # Neon Object Storage (S3-compatible).
    neon_storage_endpoint: str = ""
    neon_storage_region: str = ""
    neon_storage_access_key: str = ""
    neon_storage_secret_key: str = ""
    neon_storage_bucket: str = "resources"

    # AI providers.
    groq_api_key: str = ""
    groq_model_whisper: str = "whisper-large-v3-turbo"
    google_api_key: str = ""
    gemini_embed_model: str = "gemini-embedding-001"

    # Chat models. Each id is a setting because free catalogs change without notice.
    groq_model_fast: str = "openai/gpt-oss-20b"
    gemini_model: str = "gemini-3.5-flash-lite"
    sealion_api_key: str = ""
    sealion_model: str = "aisingapore/Qwen-SEA-LION-v4.5-27B-IT"
    # Provider order per language group; names are groq-fast, gemini, sealion.
    llm_chain_en: str = "groq-fast,gemini,sealion"
    llm_chain_other: str = "gemini,sealion,groq-fast"
    # Clustering: a pain point at or above the join similarity joins its nearest theme, below the new
    # similarity it starts one, in between an LLM agent decides. Gemini embeddings are compressed
    # (unrelated pain points still score 0.71-0.82), so these are higher than a naive 0.70 / 0.85.
    cluster_join_similarity: float = 0.90
    cluster_new_similarity: float = 0.81
    cluster_agent_max_steps: int = 4

    # An analysis run lives inside one request (300 s on Vercel), so it takes a batch of resources.
    analyze_batch_size: int = 10
    analyze_stale_minutes: int = 6  # a run with no end event after this long is treated as dead
    llm_max_wait_seconds: float = 20.0  # longest we wait for a provider's budget before skipping it

    # Local name-detection models for non-English text (blank disables a model).
    pii_malay_model: str = "mesolitica/ner-t5-small-standard-bahasa-cased"
    pii_warmup: bool = False  # load the models at startup instead of on first use

    # Ingestion limits and tools.
    max_upload_mb: int = 50

    # CORS: the deployed frontend origin (and the local dev server).
    frontend_origin: str = ""

    @property
    def cors_origins(self) -> list[str]:
        origins = ["http://localhost:5173"]
        if self.frontend_origin:
            origins.append(self.frontend_origin.rstrip("/"))
        return origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
