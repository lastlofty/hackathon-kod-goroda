from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.utils import apply_patch, commit, get_or_404, reject_null_fields
from app.models.entity import Entity
from app.models.entity_type import EntityType
from app.schemas.entity import EntityCreate, EntityRead, EntityUpdate
from app.services.attribute_validation import validate_attributes
from app.services.references import ensure_in_workspace, ensure_workspace

router = APIRouter(prefix="/entities", tags=["entities"])


@router.get("", response_model=list[EntityRead])
def list_entities(
    db: DbSession,
    workspace_id: UUID | None = None,
    entity_type_id: UUID | None = None,
    min_lat: float | None = Query(default=None, ge=-90, le=90),
    max_lat: float | None = Query(default=None, ge=-90, le=90),
    min_lon: float | None = Query(default=None, ge=-180, le=180),
    max_lon: float | None = Query(default=None, ge=-180, le=180),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Entity]:
    query = (
        select(Entity).order_by(Entity.created_at.desc()).offset(offset).limit(limit)
    )
    if workspace_id:
        query = query.where(Entity.workspace_id == workspace_id)
    if entity_type_id:
        query = query.where(Entity.entity_type_id == entity_type_id)
    if min_lat is not None:
        query = query.where(Entity.latitude >= min_lat)
    if max_lat is not None:
        query = query.where(Entity.latitude <= max_lat)
    if min_lon is not None:
        query = query.where(Entity.longitude >= min_lon)
    if max_lon is not None:
        query = query.where(Entity.longitude <= max_lon)
    return list(db.scalars(query))


@router.post("", response_model=EntityRead, status_code=status.HTTP_201_CREATED)
def create_entity(payload: EntityCreate, db: DbSession) -> Entity:
    ensure_workspace(db, payload.workspace_id)
    entity_type = ensure_in_workspace(
        db, EntityType, payload.entity_type_id, payload.workspace_id, "entity_type_id"
    )
    if entity_type:
        validate_attributes(payload.attributes, entity_type.attribute_schema)
    return commit(db, Entity(**payload.model_dump()))


@router.get("/{entity_id}", response_model=EntityRead)
def get_entity(entity_id: UUID, db: DbSession) -> Entity:
    return get_or_404(db, Entity, entity_id)


@router.patch("/{entity_id}", response_model=EntityRead)
def update_entity(entity_id: UUID, payload: EntityUpdate, db: DbSession) -> Entity:
    entity = get_or_404(db, Entity, entity_id)
    changes = payload.model_dump(exclude_unset=True)
    reject_null_fields(changes, "attributes")
    entity_type = entity.entity_type
    if "entity_type_id" in changes:
        entity_type = ensure_in_workspace(
            db,
            EntityType,
            changes["entity_type_id"],
            entity.workspace_id,
            "entity_type_id",
        )
    attributes = changes.get("attributes", entity.attributes)
    if entity_type:
        validate_attributes(attributes, entity_type.attribute_schema)
    latitude = changes.get("latitude", entity.latitude)
    longitude = changes.get("longitude", entity.longitude)
    if (latitude is None) != (longitude is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="latitude and longitude must be provided together",
        )
    return commit(db, apply_patch(entity, payload))


@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entity(entity_id: UUID, db: DbSession) -> Response:
    entity = get_or_404(db, Entity, entity_id)
    db.delete(entity)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
