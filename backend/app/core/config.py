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

    # Local name-detection models for non-English text (blank disables a model).
    pii_malay_model: str = "mesolitica/ner-t5-small-standard-bahasa-cased"
    pii_tamil_model: str = "Lokeshwaran/xlm-roberta-base-fintuned-panx-ta-hi"
    pii_warmup: bool = False  # load the models at startup instead of on first use

    # Ingestion limits and tools.
    max_upload_mb: int = 50
    tesseract_cmd: str = ""  # path to tesseract(.exe) when it is not on PATH

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
