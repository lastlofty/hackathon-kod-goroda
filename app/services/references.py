from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.api.utils import get_or_404
from app.models.workspace import Workspace


def ensure_workspace(db: Session, workspace_id: UUID) -> Workspace:
    return get_or_404(db, Workspace, workspace_id)


def ensure_in_workspace(
    db: Session,
    model: type[Any],
    entity_id: UUID | None,
    workspace_id: UUID,
    field_name: str,
) -> Any | None:
    if entity_id is None:
        return None
    entity = get_or_404(db, model, entity_id)
    if entity.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field_name} belongs to another workspace",
        )
    return entity
