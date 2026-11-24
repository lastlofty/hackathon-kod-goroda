from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.utils import apply_patch, commit, get_or_404
from app.models.asset import Asset
from app.schemas.asset import AssetCreate, AssetRead, AssetType, AssetUpdate


router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[AssetRead])
def list_assets(
    db: DbSession,
    asset_type: AssetType | None = None,
    min_lat: float | None = Query(default=None, ge=-90, le=90),
    max_lat: float | None = Query(default=None, ge=-90, le=90),
    min_lon: float | None = Query(default=None, ge=-180, le=180),
    max_lon: float | None = Query(default=None, ge=-180, le=180),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Asset]:
    query = select(Asset).order_by(Asset.created_at.desc()).offset(offset).limit(limit)
    if asset_type:
        query = query.where(Asset.asset_type == asset_type.value)
    if min_lat is not None:
        query = query.where(Asset.latitude >= min_lat)
    if max_lat is not None:
        query = query.where(Asset.latitude <= max_lat)
    if min_lon is not None:
        query = query.where(Asset.longitude >= min_lon)
    if max_lon is not None:
        query = query.where(Asset.longitude <= max_lon)
    return list(db.scalars(query))


@router.post("", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
def create_asset(payload: AssetCreate, db: DbSession) -> Asset:
    return commit(db, Asset(**payload.model_dump()))


@router.get("/{asset_id}", response_model=AssetRead)
def get_asset(asset_id: UUID, db: DbSession) -> Asset:
    return get_or_404(db, Asset, asset_id)


@router.patch("/{asset_id}", response_model=AssetRead)
def update_asset(asset_id: UUID, payload: AssetUpdate, db: DbSession) -> Asset:
    asset = get_or_404(db, Asset, asset_id)
    return commit(db, apply_patch(asset, payload))


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(asset_id: UUID, db: DbSession) -> Response:
    asset = get_or_404(db, Asset, asset_id)
    db.delete(asset)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
