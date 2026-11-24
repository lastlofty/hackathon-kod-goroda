from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.utils import apply_patch, commit, get_or_404
from app.models.asset import Asset
from app.models.inspection import Inspection
from app.models.media import Media
from app.schemas.inspection import Condition, InspectionCreate, InspectionRead, InspectionUpdate


router = APIRouter(prefix="/inspections", tags=["inspections"])


def validate_references(db: DbSession, asset_id: UUID, media_id: UUID | None) -> None:
    get_or_404(db, Asset, asset_id)
    if media_id is not None:
        get_or_404(db, Media, media_id)


@router.get("", response_model=list[InspectionRead])
def list_inspections(
    db: DbSession,
    asset_id: UUID | None = None,
    media_id: UUID | None = None,
    condition: Condition | None = None,
    reviewed: bool | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Inspection]:
    query = select(Inspection).order_by(Inspection.observed_at.desc()).offset(offset).limit(limit)
    if asset_id:
        query = query.where(Inspection.asset_id == asset_id)
    if media_id:
        query = query.where(Inspection.media_id == media_id)
    if condition:
        query = query.where(Inspection.condition == condition.value)
    if reviewed is not None:
        query = query.where(Inspection.reviewed == reviewed)
    return list(db.scalars(query))


@router.post("", response_model=InspectionRead, status_code=status.HTTP_201_CREATED)
def create_inspection(payload: InspectionCreate, db: DbSession) -> Inspection:
    validate_references(db, payload.asset_id, payload.media_id)
    data = payload.model_dump()
    if data["observed_at"] is None:
        data.pop("observed_at")
    return commit(db, Inspection(**data))


@router.get("/{inspection_id}", response_model=InspectionRead)
def get_inspection(inspection_id: UUID, db: DbSession) -> Inspection:
    return get_or_404(db, Inspection, inspection_id)


@router.patch("/{inspection_id}", response_model=InspectionRead)
def update_inspection(
    inspection_id: UUID, payload: InspectionUpdate, db: DbSession
) -> Inspection:
    inspection = get_or_404(db, Inspection, inspection_id)
    changes = payload.model_dump(exclude_unset=True)
    validate_references(
        db,
        changes.get("asset_id", inspection.asset_id),
        changes.get("media_id", inspection.media_id),
    )
    return commit(db, apply_patch(inspection, payload))


@router.delete("/{inspection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_inspection(inspection_id: UUID, db: DbSession) -> Response:
    inspection = get_or_404(db, Inspection, inspection_id)
    db.delete(inspection)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
