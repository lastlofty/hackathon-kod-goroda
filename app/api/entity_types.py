from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.utils import apply_patch, commit, get_or_404
from app.models.entity_type import EntityType
from app.schemas.entity_type import EntityTypeCreate, EntityTypeRead, EntityTypeUpdate
from app.services.attribute_validation import validate_schema
from app.services.references import ensure_workspace

router = APIRouter(prefix="/entity-types", tags=["entity types"])


@router.get("", response_model=list[EntityTypeRead])
def list_entity_types(
    db: DbSession,
    workspace_id: UUID | None = None,
    active: bool | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[EntityType]:
    query = (
        select(EntityType)
        .order_by(EntityType.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if workspace_id:
        query = query.where(EntityType.workspace_id == workspace_id)
    if active is not None:
        query = query.where(EntityType.active == active)
    return list(db.scalars(query))


@router.post("", response_model=EntityTypeRead, status_code=status.HTTP_201_CREATED)
def create_entity_type(payload: EntityTypeCreate, db: DbSession) -> EntityType:
    ensure_workspace(db, payload.workspace_id)
    validate_schema(payload.attribute_schema)
    return commit(db, EntityType(**payload.model_dump()))


@router.get("/{entity_type_id}", response_model=EntityTypeRead)
def get_entity_type(entity_type_id: UUID, db: DbSession) -> EntityType:
    return get_or_404(db, EntityType, entity_type_id)


@router.patch("/{entity_type_id}", response_model=EntityTypeRead)
def update_entity_type(
    entity_type_id: UUID, payload: EntityTypeUpdate, db: DbSession
) -> EntityType:
    entity_type = get_or_404(db, EntityType, entity_type_id)
    if payload.attribute_schema is not None:
        validate_schema(payload.attribute_schema)
    return commit(db, apply_patch(entity_type, payload))


@router.delete("/{entity_type_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entity_type(entity_type_id: UUID, db: DbSession) -> Response:
    entity_type = get_or_404(db, EntityType, entity_type_id)
    db.delete(entity_type)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
