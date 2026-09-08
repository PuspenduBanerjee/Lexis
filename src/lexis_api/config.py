"""Application settings, overridable via environment variables (prefix LEXIS_)."""

import tempfile

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEXIS_")

    database_url: str = "sqlite:///./lexis_dev.db"
    cors_origins: list[str] = ["http://localhost:5173"]
    default_user_id: int = 1
    max_duckdb_upload_mb: int = 50
    upload_tmp_dir: str = tempfile.gettempdir()
    max_result_rows: int = 1000
    # Dev-only: when set (e.g. "http://localhost:5173"), mounts a catch-all proxy
    # to the Vite dev server so this app's own port serves both the API and the
    # UI - see dev_proxy.py. Unset in production (nginx serves the built
    # frontend there instead - docker/nginx.conf).
    dev_ui_proxy_target: str | None = None


settings = Settings()
