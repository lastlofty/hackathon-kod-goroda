from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import EntityRead


class Condition(StrEnum):
    NORMAL = "normal"
    ATTENTION = "attention"
    REPAIR = "repair"
    CRITICAL = "critical"


class InspectionCreate(BaseModel):
    asset_id: UUID
    media_id: UUID | None = None
    observed_at: datetime | None = None
    condition: Condition
    defect_type: str | None = Field(default=None, max_length=128)
    confidence: float = Field(ge=0, le=1)
    severity: int = Field(default=0, ge=0, le=100)
    recommendation: str | None = None
    bbox: dict[str, Any] | None = None
    model_name: str | None = Field(default=None, max_length=128)
    model_version: str | None = Field(default=None, max_length=64)
    reviewed: bool = False


class InspectionUpdate(BaseModel):
    asset_id: UUID | None = None
    media_id: UUID | None = None
    observed_at: datetime | None = None
    condition: Condition | None = None
    defect_type: str | None = Field(default=None, max_length=128)
    confidence: float | None = Field(default=None, ge=0, le=1)
    severity: int | None = Field(default=None, ge=0, le=100)
    recommendation: str | None = None
    bbox: dict[str, Any] | None = None
    model_name: str | None = Field(default=None, max_length=128)
    model_version: str | None = Field(default=None, max_length=64)
    reviewed: bool | None = None


class InspectionRead(EntityRead):
    asset_id: UUID
    media_id: UUID | None
    observed_at: datetime
    condition: Condition
    defect_type: str | None
    confidence: float
    severity: int
    recommendation: str | None
    bbox: dict[str, Any] | None
    model_name: str | None
    model_version: str | None
    reviewed: bool
