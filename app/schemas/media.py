from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import EntityRead as BaseEntityRead


class MediaCreate(BaseModel):
    workspace_id: UUID
    kind: str = Field(default="image", min_length=1, max_length=64)
    url: str
    original_filename: str | None = Field(default=None, max_length=500)
    content_type: str | None = Field(default=None, max_length=128)
    captured_at: datetime | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    source: str | None = Field(default=None, max_length=128)
    attributes: dict[str, Any] = Field(default_factory=dict)


class MediaUpdate(BaseModel):
    kind: str | None = Field(default=None, min_length=1, max_length=64)
    url: str | None = None
    original_filename: str | None = Field(default=None, max_length=500)
    content_type: str | None = Field(default=None, max_length=128)
    captured_at: datetime | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    source: str | None = Field(default=None, max_length=128)
    attributes: dict[str, Any] | None = None


class MediaRead(BaseEntityRead, MediaCreate):
    pass
