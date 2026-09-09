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
    # Dev convenience: when true (LEXIS_DEV_SETUP_DEMO=1), startup writes the bundled
    # demo datasets to real .duckdb files under demo_data_dir and registers a
    # `duckdb_file` connection for each ("tpcds-demo", "retail-demo") - so the MCP
    # endpoint and the Run tab have working connections with no manual curl. Both
    # steps are idempotent. Leave off in production: it writes files and DB rows on
    # every boot. See seed.seed_demo_connections.
    dev_setup_demo: bool = False
    demo_data_dir: str = tempfile.gettempdir()
    # Dev-only: when set (e.g. "http://localhost:5173"), mounts a catch-all proxy
    # to the Vite dev server so this app's own port serves both the API and the
    # UI - see dev_proxy.py. Unset in production (nginx serves the built
    # frontend there instead - docker/nginx.conf).
    dev_ui_proxy_target: str | None = None
    # Single-image mode: when set to the Vite build output directory, this app
    # also serves the built frontend from `/` (with SPA deep-link fallback), so
    # one container exposes both the API and the UI - see static.py and
    # docker/allinone.Dockerfile. Unset for a plain API/library install or the
    # split api+nginx compose setup (docker/nginx.conf serves the frontend there).
    frontend_dist_dir: str | None = None


settings = Settings()
