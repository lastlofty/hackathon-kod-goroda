from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.common import EntityRead


class MediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    FRAME = "frame"


class MediaCreate(BaseModel):
    media_type: MediaType = MediaType.IMAGE
    url: str
    original_filename: str | None = Field(default=None, max_length=500)
    content_type: str | None = Field(default=None, max_length=128)
    captured_at: datetime | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    source: str | None = Field(default=None, max_length=128)


class MediaUpdate(BaseModel):
    media_type: MediaType | None = None
    url: str | None = None
    original_filename: str | None = Field(default=None, max_length=500)
    content_type: str | None = Field(default=None, max_length=128)
    captured_at: datetime | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    source: str | None = Field(default=None, max_length=128)


class MediaRead(EntityRead, MediaCreate):
    pass
