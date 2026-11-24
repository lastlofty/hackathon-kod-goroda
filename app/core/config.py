from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Case-Agnostic Backend Starter"
    database_url: str = "postgresql+psycopg://app:app@localhost:5432/app"
    triton_url: str = "http://localhost:8000"
    upload_dir: Path = Path("uploads")
    max_upload_size_mb: int = Field(default=25, ge=1, le=500)
    dgis_api_key: SecretStr | None = None
    dgis_base_url: str = "https://catalog.api.2gis.com"
    dgis_locale: str = "ru_RU"
    dgis_timeout_seconds: float = Field(default=30, gt=0, le=60)


@lru_cache
def get_settings() -> Settings:
    return Settings()
