from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Case-Agnostic Backend Starter"
    database_url: str = "postgresql+psycopg://app:app@localhost:5432/app"
    triton_url: str = "http://localhost:8000"
    inference_mode: Literal["disabled", "mock", "triton"] = "disabled"
    triton_model_name: str = "detection"
    triton_model_version: str = "1"
    triton_timeout_seconds: float = Field(default=30, gt=0, le=120)
    upload_dir: Path = Path("uploads")
    max_upload_size_mb: int = Field(default=25, ge=1, le=500)
    backend_bind: str = "127.0.0.1"
    access_password: SecretStr | None = None
    public_origin: str = ""
    dgis_browser_key: str = ""
    dgis_api_key: SecretStr | None = None
    dgis_base_url: str = "https://catalog.api.2gis.com"
    dgis_locale: str = "ru_RU"
    dgis_timeout_seconds: float = Field(default=30, gt=0, le=60)

    frontend_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:8778", "http://127.0.0.1:8778"]
    )

    @field_validator("access_password", mode="before")
    @classmethod
    def unset_empty_password(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_access(self):
        if self.access_password is None:
            if self.backend_bind not in {"127.0.0.1", "::1", "[::1]"}:
                raise ValueError("A non-loopback BACKEND_BIND requires ACCESS_PASSWORD")
            return self
        if len(self.access_password.get_secret_value()) < 24:
            raise ValueError("ACCESS_PASSWORD must contain at least 24 characters")
        origin = urlsplit(self.public_origin)
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.username is not None
            or origin.password is not None
            or self.public_origin != f"https://{origin.netloc}"
        ):
            raise ValueError("PUBLIC_ORIGIN must be an HTTPS origin without a path")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
