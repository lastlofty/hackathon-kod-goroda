from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.utils import apply_patch, commit, get_or_404, reject_null_fields
from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceCreate, WorkspaceRead, WorkspaceUpdate

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceRead])
def list_workspaces(
    db: DbSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Workspace]:
    query = (
        select(Workspace)
        .order_by(Workspace.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(db.scalars(query))


@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
def create_workspace(payload: WorkspaceCreate, db: DbSession) -> Workspace:
    return commit(db, Workspace(**payload.model_dump()))


@router.get("/{workspace_id}", response_model=WorkspaceRead)
def get_workspace(workspace_id: UUID, db: DbSession) -> Workspace:
    return get_or_404(db, Workspace, workspace_id)


@router.patch("/{workspace_id}", response_model=WorkspaceRead)
def update_workspace(
    workspace_id: UUID, payload: WorkspaceUpdate, db: DbSession
) -> Workspace:
    workspace = get_or_404(db, Workspace, workspace_id)
    reject_null_fields(payload.model_dump(exclude_unset=True), "slug", "name", "settings")
    return commit(db, apply_patch(workspace, payload))


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(workspace_id: UUID, db: DbSession) -> Response:
    workspace = get_or_404(db, Workspace, workspace_id)
    db.delete(workspace)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
