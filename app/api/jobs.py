from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.utils import apply_patch, commit, get_or_404, reject_null_fields
from app.core.config import get_settings
from app.models.job import ProcessingJob
from app.models.media import Media
from app.schemas.job import JobCreate, JobRead, JobUpdate
from app.services.inference import run_job
from app.services.references import ensure_in_workspace, ensure_workspace

router = APIRouter(prefix="/jobs", tags=["processing jobs"])


@router.get("", response_model=list[JobRead])
def list_jobs(
    db: DbSession,
    workspace_id: UUID | None = None,
    status_value: str | None = Query(default=None, alias="status"),
    pipeline: str | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ProcessingJob]:
    query = (
        select(ProcessingJob)
        .order_by(ProcessingJob.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if workspace_id:
        query = query.where(ProcessingJob.workspace_id == workspace_id)
    if status_value:
        query = query.where(ProcessingJob.status == status_value)
    if pipeline:
        query = query.where(ProcessingJob.pipeline == pipeline)
    return list(db.scalars(query))


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def create_job(payload: JobCreate, db: DbSession) -> ProcessingJob:
    ensure_workspace(db, payload.workspace_id)
    ensure_in_workspace(db, Media, payload.media_id, payload.workspace_id, "media_id")
    return commit(db, ProcessingJob(**payload.model_dump()))


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: UUID, db: DbSession) -> ProcessingJob:
    return get_or_404(db, ProcessingJob, job_id)


@router.patch("/{job_id}", response_model=JobRead)
def update_job(job_id: UUID, payload: JobUpdate, db: DbSession) -> ProcessingJob:
    job = get_or_404(db, ProcessingJob, job_id)
    changes = payload.model_dump(exclude_unset=True)
    reject_null_fields(changes, "pipeline", "status", "parameters", "result")
    if "media_id" in changes:
        ensure_in_workspace(
            db, Media, changes["media_id"], job.workspace_id, "media_id"
        )
    return commit(db, apply_patch(job, payload))


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: UUID, db: DbSession) -> Response:
    job = get_or_404(db, ProcessingJob, job_id)
    db.delete(job)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{job_id}/run", response_model=JobRead)
def execute_job(job_id: UUID, db: DbSession) -> ProcessingJob:
    return run_job(db, job_id, get_settings())
