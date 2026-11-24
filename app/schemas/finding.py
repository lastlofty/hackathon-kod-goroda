from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import EntityRead as BaseEntityRead


class FindingCreate(BaseModel):
    workspace_id: UUID
    entity_id: UUID | None = None
    media_id: UUID | None = None
    job_id: UUID | None = None
    observed_at: datetime | None = None
    category: str = Field(min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, max_length=64)
    score: float | None = Field(default=None, ge=0, le=1)
    severity: float | None = None
    recommendation: str | None = None
    geometry: dict[str, Any] | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    source: str | None = Field(default=None, max_length=128)
    reviewed: bool = False


class FindingUpdate(BaseModel):
    entity_id: UUID | None = None
    media_id: UUID | None = None
    job_id: UUID | None = None
    observed_at: datetime | None = None
    category: str | None = Field(default=None, min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, max_length=64)
    score: float | None = Field(default=None, ge=0, le=1)
    severity: float | None = None
    recommendation: str | None = None
    geometry: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None
    source: str | None = Field(default=None, max_length=128)
    reviewed: bool | None = None


class FindingRead(BaseEntityRead):
    workspace_id: UUID
    entity_id: UUID | None
    media_id: UUID | None
    job_id: UUID | None
    observed_at: datetime
    category: str
    label: str | None
    status: str | None
    score: float | None
    severity: float | None
    recommendation: str | None
    geometry: dict[str, Any] | None
    attributes: dict[str, Any]
    source: str | None
    reviewed: bool
