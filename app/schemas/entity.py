from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import EntityRead as BaseEntityRead


class EntityCreate(BaseModel):
    workspace_id: UUID
    entity_type_id: UUID | None = None
    external_id: str | None = Field(default=None, max_length=128)
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    geometry: dict[str, Any] | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def coordinates_are_a_pair(self) -> "EntityCreate":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class EntityUpdate(BaseModel):
    entity_type_id: UUID | None = None
    external_id: str | None = Field(default=None, max_length=128)
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    attributes: dict[str, Any] | None = None
    geometry: dict[str, Any] | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class EntityRead(BaseEntityRead, EntityCreate):
    pass
