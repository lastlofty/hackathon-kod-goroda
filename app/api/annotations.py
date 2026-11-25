from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.utils import commit, get_or_404
from app.models.annotation import AnnotationRevision
from app.models.media import Media
from app.schemas.annotation import AnnotationUpdate, RevisionInfo, RevisionRead

router = APIRouter(prefix="/media", tags=["annotations"])


@router.get("/{media_id}/annotations", response_model=list[RevisionInfo])
def revisions(media_id: UUID, db: DbSession, limit: Annotated[int, Query(ge=1, le=100)] = 25):
    get_or_404(db, Media, media_id)
    query = select(AnnotationRevision).where(AnnotationRevision.media_id == media_id)
    return db.scalars(query.order_by(AnnotationRevision.version.desc()).limit(limit)).all()


@router.post("/{media_id}/annotations", response_model=RevisionRead, status_code=201)
def save_annotations(media_id: UUID, payload: AnnotationUpdate, db: DbSession):
    get_or_404(db, Media, media_id)
    query = select(AnnotationRevision).where(AnnotationRevision.media_id == media_id)
    latest = db.scalar(query.order_by(AnnotationRevision.version.desc()).limit(1))
    changes = payload.model_dump(mode="json")["changes"]
    version = latest.version if latest else 0
    if version != payload.base_version:
        if (latest and version == payload.base_version + 1 and latest.author == payload.author
                and set(latest.changed_ids) == changes.keys()
                and all(latest.overrides[key] == shape for key, shape in changes.items())):
            return latest
        raise HTTPException(409, "Annotation version changed")
    # The composite primary key also rejects a concurrent insert based on the same version.
    return commit(db, AnnotationRevision(
        media_id=media_id, version=version + 1, author=payload.author,
        overrides={**(latest.overrides if latest else {}), **changes}, changed_ids=list(changes),
    ))
