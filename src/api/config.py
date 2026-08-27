"""Application configuration loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# All API routes are mounted under this prefix.
API_PREFIX = "/api"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Postgres -----------------------------------------------------------
    postgres_host: str
    postgres_port: int = 5432
    postgres_db: str
    postgres_schema: str = "public"
    postgres_auth_method: str = "entra"  # "entra" | "password"
    postgres_user: str
    postgres_password: str = ""
    postgres_sslmode: str = "verify-full"
    postgres_sslrootcert: str | None = None
    postgres_connect_timeout: int = 30
    postgres_pool_min: int = 1
    postgres_pool_max: int = 16
    # Set when connecting through the built-in PgBouncer of Azure Database for
    # PostgreSQL (port 6432). Its transaction pooling mode drops session state
    # between statements, so session settings move into the startup options and
    # server-side prepared statements are disabled.
    postgres_pgbouncer: bool = False
    # Ceiling on any single statement, so a runaway query cannot pin a pool slot.
    postgres_statement_timeout_ms: int = 15000
    # Image search reads the upload into memory before embedding it.
    max_upload_bytes: int = 10 * 1024 * 1024

    # --- Rate limiting ------------------------------------------------------
    # Image search calls a metered embedding API, so cap it per client. The
    # limiter is per replica, so the real ceiling is this times the replica count.
    image_search_rate_limit: int = 10
    image_search_rate_window_seconds: int = 60
    # Rendering a form reads every label blob and rasterises them; cheaper than
    # the embedding call, but still worth a ceiling.
    form_render_rate_limit: int = 30
    form_render_rate_window_seconds: int = 60
    # Only enable behind a reverse proxy that overwrites X-Forwarded-For;
    # otherwise clients can spoof the header and reset their own bucket.
    trust_forwarded_for: bool = True

    # --- Blob storage (label images) ---------------------------------------
    blob_account_url: str | None = None
    blob_container: str | None = None

    # --- Embedding provider (pluggable) ------------------------------------
    embedding_provider: str = "gemini"
    embedding_model: str = "gemini-embedding-2"
    embedding_dim: int = 768
    gemini_api_key: str | None = None

    # --- Telemetry / analytics ---------------------------------------------
    # Absent connection string == telemetry disabled, which is what local dev
    # and the test suite rely on. Never fail startup over telemetry.
    applicationinsights_connection_string: str | None = None
    telemetry_enabled: bool = True
    telemetry_sampling_ratio: float = 1.0
    # Free-text search input is user-supplied content on a public site; only
    # derived attributes (length, term count) are recorded unless this is on.
    analytics_capture_query_text: bool = False
    # Salt for hashing the client address when no client-supplied session id is
    # present. Rotate to break linkability across deployments.
    analytics_salt: str = ""

    # --- Usage dashboard ----------------------------------------------------
    # The /analytics page is unlisted, not authenticated, so it stays opt-in.
    analytics_dashboard_enabled: bool = False
    # Log Analytics workspace GUID (customerId). Not carried by the App Insights
    # connection string, so it is passed separately.
    log_analytics_workspace_id: str | None = None
    # Dashboard numbers move slowly and every miss costs a Log Analytics query.
    analytics_dashboard_cache_seconds: int = 900
    analytics_dashboard_rate_limit: int = 30
    analytics_dashboard_rate_window_seconds: int = 60

    # --- API ----------------------------------------------------------------
    api_title: str = "TTB COLA Search API"
    cors_origins: str = "*"
    # Directory of the built Vite SPA (dist). When set and present, FastAPI
    # serves the SPA at "/" so the app runs single-origin (no CORS in prod).
    # In the container this is set to the copied build output; unset locally.
    spa_dir: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
