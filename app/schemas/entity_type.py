from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import EntityRead as BaseEntityRead


class EntityTypeCreate(BaseModel):
    workspace_id: UUID
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    attribute_schema: dict[str, Any] = Field(default_factory=dict)
    active: bool = True


class EntityTypeUpdate(BaseModel):
    code: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    attribute_schema: dict[str, Any] | None = None
    active: bool | None = None


class EntityTypeRead(BaseEntityRead, EntityTypeCreate):
    pass
