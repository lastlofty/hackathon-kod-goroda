from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.common import EntityRead


class AssetType(StrEnum):
    CABLE_WELL = "cable_well"
    DUAL_PURPOSE_SUPPORT = "dual_purpose_support"
    OTHER = "other"


class AssetCreate(BaseModel):
    external_id: str | None = Field(default=None, max_length=128)
    asset_type: AssetType
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    address: str | None = Field(default=None, max_length=500)


class AssetUpdate(BaseModel):
    external_id: str | None = Field(default=None, max_length=128)
    asset_type: AssetType | None = None
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    address: str | None = Field(default=None, max_length=500)


class AssetRead(EntityRead, AssetCreate):
    pass
