from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.utils import apply_patch, commit, get_or_404
from app.models.entity import Entity
from app.models.finding import Finding
from app.models.job import ProcessingJob
from app.models.media import Media
from app.schemas.finding import FindingCreate, FindingRead, FindingUpdate
from app.services.references import ensure_in_workspace, ensure_workspace

router = APIRouter(prefix="/findings", tags=["findings"])


def validate_references(
    db: DbSession,
    workspace_id: UUID,
    entity_id: UUID | None,
    media_id: UUID | None,
    job_id: UUID | None,
) -> None:
    ensure_workspace(db, workspace_id)
    ensure_in_workspace(db, Entity, entity_id, workspace_id, "entity_id")
    ensure_in_workspace(db, Media, media_id, workspace_id, "media_id")
    ensure_in_workspace(db, ProcessingJob, job_id, workspace_id, "job_id")


@router.get("", response_model=list[FindingRead])
def list_findings(
    db: DbSession,
    workspace_id: UUID | None = None,
    entity_id: UUID | None = None,
    media_id: UUID | None = None,
    job_id: UUID | None = None,
    category: str | None = None,
    status_value: str | None = Query(default=None, alias="status"),
    reviewed: bool | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Finding]:
    query = (
        select(Finding).order_by(Finding.observed_at.desc()).offset(offset).limit(limit)
    )
    filters = {
        Finding.workspace_id: workspace_id,
        Finding.entity_id: entity_id,
        Finding.media_id: media_id,
        Finding.job_id: job_id,
        Finding.category: category,
        Finding.status: status_value,
        Finding.reviewed: reviewed,
    }
    for column, value in filters.items():
        if value is not None:
            query = query.where(column == value)
    return list(db.scalars(query))


@router.post("", response_model=FindingRead, status_code=status.HTTP_201_CREATED)
def create_finding(payload: FindingCreate, db: DbSession) -> Finding:
    validate_references(
        db, payload.workspace_id, payload.entity_id, payload.media_id, payload.job_id
    )
    data = payload.model_dump()
    if data["observed_at"] is None:
        data.pop("observed_at")
    return commit(db, Finding(**data))


@router.get("/{finding_id}", response_model=FindingRead)
def get_finding(finding_id: UUID, db: DbSession) -> Finding:
    return get_or_404(db, Finding, finding_id)


@router.patch("/{finding_id}", response_model=FindingRead)
def update_finding(finding_id: UUID, payload: FindingUpdate, db: DbSession) -> Finding:
    finding = get_or_404(db, Finding, finding_id)
    changes = payload.model_dump(exclude_unset=True)
    validate_references(
        db,
        finding.workspace_id,
        changes.get("entity_id", finding.entity_id),
        changes.get("media_id", finding.media_id),
        changes.get("job_id", finding.job_id),
    )
    return commit(db, apply_patch(finding, payload))


@router.delete("/{finding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_finding(finding_id: UUID, db: DbSession) -> Response:
    finding = get_or_404(db, Finding, finding_id)
    db.delete(finding)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
