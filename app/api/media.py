from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.utils import apply_patch, commit, get_or_404
from app.core.config import get_settings
from app.models.media import Media
from app.schemas.media import MediaCreate, MediaRead, MediaUpdate
from app.services.references import ensure_workspace

router = APIRouter(prefix="/media", tags=["media"])
settings = get_settings()
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


@router.get("", response_model=list[MediaRead])
def list_media(
    db: DbSession,
    workspace_id: UUID | None = None,
    kind: str | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Media]:
    query = select(Media).order_by(Media.created_at.desc()).offset(offset).limit(limit)
    if workspace_id:
        query = query.where(Media.workspace_id == workspace_id)
    if kind:
        query = query.where(Media.kind == kind)
    return list(db.scalars(query))


@router.post("", response_model=MediaRead, status_code=status.HTTP_201_CREATED)
def create_media(payload: MediaCreate, db: DbSession) -> Media:
    ensure_workspace(db, payload.workspace_id)
    return commit(db, Media(**payload.model_dump()))


@router.post("/upload", response_model=MediaRead, status_code=status.HTTP_201_CREATED)
async def upload_image(
    db: DbSession,
    file: Annotated[UploadFile, File()],
    workspace_id: Annotated[UUID, Form()],
    kind: Annotated[str, Form(min_length=1, max_length=64)] = "image",
    captured_at: Annotated[datetime | None, Form()] = None,
    latitude: Annotated[float | None, Form(ge=-90, le=90)] = None,
    longitude: Annotated[float | None, Form(ge=-180, le=180)] = None,
    source: Annotated[str | None, Form(max_length=128)] = None,
) -> Media:
    ensure_workspace(db, workspace_id)
    if (latitude is None) != (longitude is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="latitude and longitude must be provided together",
        )
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=415, detail="Only JPEG, PNG and WebP images are supported"
        )

    content = await file.read(settings.max_upload_size_mb * 1024 * 1024 + 1)
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File is too large")

    signatures = {
        "image/jpeg": (content.startswith(b"\xff\xd8\xff"), ".jpg"),
        "image/png": (content.startswith(b"\x89PNG\r\n\x1a\n"), ".png"),
        "image/webp": (content[:4] == b"RIFF" and content[8:12] == b"WEBP", ".webp"),
    }
    valid, suffix = signatures[file.content_type]
    if not valid:
        raise HTTPException(status_code=415, detail="File contents do not match image type")
    filename = f"{uuid4()}{suffix}"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    destination = settings.upload_dir / filename
    destination.write_bytes(content)

    media = Media(
        workspace_id=workspace_id,
        kind=kind,
        url=f"/uploads/{filename}",
        original_filename=file.filename,
        content_type=file.content_type,
        captured_at=captured_at,
        latitude=latitude,
        longitude=longitude,
        source=source,
    )
    return commit(db, media)


@router.get("/{media_id}", response_model=MediaRead)
def get_media(media_id: UUID, db: DbSession) -> Media:
    return get_or_404(db, Media, media_id)


@router.patch("/{media_id}", response_model=MediaRead)
def update_media(media_id: UUID, payload: MediaUpdate, db: DbSession) -> Media:
    media = get_or_404(db, Media, media_id)
    return commit(db, apply_patch(media, payload))


@router.delete("/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_media(media_id: UUID, db: DbSession) -> Response:
    media = get_or_404(db, Media, media_id)
    db.delete(media)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
