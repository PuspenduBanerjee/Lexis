"""Application settings, overridable via environment variables (prefix SEMANTICA_)."""

import tempfile

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SEMANTICA_")

    database_url: str = "sqlite:///./semantica_dev.db"
    cors_origins: list[str] = ["http://localhost:5173"]
    default_user_id: int = 1
    max_duckdb_upload_mb: int = 50
    upload_tmp_dir: str = tempfile.gettempdir()
    max_result_rows: int = 1000


settings = Settings()
