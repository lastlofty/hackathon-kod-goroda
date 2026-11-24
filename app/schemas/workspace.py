from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import EntityRead as BaseEntityRead


class WorkspaceCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class WorkspaceUpdate(BaseModel):
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    settings: dict[str, Any] | None = None


class WorkspaceRead(BaseEntityRead, WorkspaceCreate):
    pass
