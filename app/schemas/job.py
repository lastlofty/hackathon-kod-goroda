from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import EntityRead as BaseEntityRead


class JobCreate(BaseModel):
    workspace_id: UUID
    media_id: UUID | None = None
    pipeline: str = Field(min_length=1, max_length=128)
    status: str = Field(default="queued", min_length=1, max_length=32)
    parameters: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobUpdate(BaseModel):
    media_id: UUID | None = None
    pipeline: str | None = Field(default=None, min_length=1, max_length=128)
    status: str | None = Field(default=None, min_length=1, max_length=32)
    parameters: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobRead(BaseEntityRead, JobCreate):
    pass
