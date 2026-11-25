"""Read the same inspection data as a JSON batch or as server-sent changes."""
import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.db.session import SessionLocal
from app.models.annotation import AnnotationRevision
from app.models.entity import Entity
from app.models.entity_type import EntityType
from app.models.finding import Finding
from app.models.media import Media
from app.models.workspace import Workspace
from app.schemas.annotation import RevisionRead
from app.schemas.entity import EntityRead
from app.schemas.entity_type import EntityTypeRead
from app.schemas.finding import FindingRead
from app.schemas.media import MediaRead

router = APIRouter(prefix="/inspection", tags=["inspection"])
COLLECTIONS = ("frames", "entities", "types", "standalone_findings")


def rows(db, workspace_id: UUID, model, schema):
    query = select(model).where(model.workspace_id == workspace_id).order_by(model.id)
    return {str(row.id): schema.model_validate(row).model_dump(mode="json") for row in db.scalars(query)}


def snapshot(db: Session, slug: str) -> dict:
    workspace_id = db.scalar(select(Workspace.id).where(Workspace.slug == slug))
    result = {key: {} for key in COLLECTIONS}
    if workspace_id is None:
        return result
    frames = rows(db, workspace_id, Media, MediaRead)
    for frame in frames.values():
        frame["findings"] = []
        frame["annotation_review"] = None
    latest = (select(AnnotationRevision.media_id, func.max(AnnotationRevision.version).label("version"))
              .join(Media).where(Media.workspace_id == workspace_id)
              .group_by(AnnotationRevision.media_id).subquery())
    review_query = select(AnnotationRevision).join(latest, and_(
        AnnotationRevision.media_id == latest.c.media_id, AnnotationRevision.version == latest.c.version))
    for review in db.scalars(review_query):
        frame = frames.get(str(review.media_id))
        if frame is not None:
            frame["annotation_review"] = RevisionRead.model_validate(review).model_dump(mode="json")
    result["frames"] = frames
    result["types"] = rows(db, workspace_id, EntityType, EntityTypeRead)
    result["entities"] = rows(db, workspace_id, Entity, EntityRead)
    for key, finding in rows(db, workspace_id, Finding, FindingRead).items():
        frame = frames.get(finding["media_id"])
        if frame is None:
            result["standalone_findings"][key] = finding
        else:
            frame["findings"].append(finding)
    return result


def batch(data):
    return {"supports_annotation_revisions": True, **{key: list(values.values()) for key, values in data.items()}}


def changes(previous, current):
    updated, removed = {}, {}
    for key in COLLECTIONS:
        after, before = current[key], previous[key]
        modified = [row for i, row in after.items() if before.get(i) != row]
        missing = sorted(before.keys() - after.keys())
        if modified:
            updated[key] = modified
        if missing:
            removed[key] = missing
    return {"upsert": updated, "remove": removed} if updated or removed else None


@router.get("/frames")
def inspection_frames(db: DbSession, workspace: str = Query(min_length=1, max_length=128)):
    return batch(snapshot(db, workspace))


@router.get("/stream")
async def inspection_stream(request: Request, workspace: str = Query(min_length=1, max_length=128)):
    def read():
        with SessionLocal() as db:
            return snapshot(db, workspace)

    async def events():
        previous = None
        idle = 0
        while not await request.is_disconnected():
            current = await run_in_threadpool(read)
            payload = batch(current) if previous is None else changes(previous, current)
            if payload is not None:
                name = "batch" if previous is None else "changes"
                yield f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
                idle = 0
            elif idle >= 7:
                yield ": heartbeat\n\n"
                idle = 0
            previous = current
            idle += 1
            await asyncio.sleep(2)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })
