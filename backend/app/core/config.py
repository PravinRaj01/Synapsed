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
