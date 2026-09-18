"""Central application settings (R02).

All environment-driven config lives here, validated by pydantic-settings.
Import `settings` and read attributes instead of calling os.getenv.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# The shipped default JWT secret (TA1-2). It is PUBLIC knowledge (lives in the
# repo), so signing tokens with it means anyone can forge a session. Startup
# refuses to boot with it outside dev/test mode — see app.lifespan.
JWT_SECRET_KEY_DEFAULT = "super-secret-change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "sqlite:///./stw.db"

    # Auth / JWT
    jwt_secret_key: str = JWT_SECRET_KEY_DEFAULT
    cookie_secure: bool = False

    # CORS — comma-separated list, or empty for local defaults.
    cors_origins: str = ""

    # File uploads
    upload_dir: str = "./uploads"
    max_upload_mb: float = 25.0

    @property
    def max_upload_bytes(self) -> int:
        """Server-side upload cap in bytes (MAX_UPLOAD_MB, default 25 MB)."""
        return int(self.max_upload_mb * 1024 * 1024)

    # AI assistant
    ai_provider_api_key: str | None = None
    ai_provider_base_url: str | None = None
    ai_provider_model: str = "gpt-4o-mini"

    # Observability (TA6-1): statements at/over this many ms get a
    # ``slow_query`` WARNING (fingerprint only, never params).
    slow_query_threshold_ms: float = 200.0

    def cors_origin_list(self) -> list[str]:
        if self.cors_origins:
            return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return [
            "http://localhost:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
