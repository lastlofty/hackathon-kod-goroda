from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "MGTS Infrastructure Monitor"
    database_url: str = "postgresql+psycopg://mgts:mgts@localhost:5432/mgts"
    triton_url: str = "http://localhost:8000"
    upload_dir: Path = Path("uploads")
    max_upload_size_mb: int = Field(default=25, ge=1, le=500)


@lru_cache
def get_settings() -> Settings:
    return Settings()
