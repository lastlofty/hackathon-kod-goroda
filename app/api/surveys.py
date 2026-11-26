from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal
from uuid import UUID, uuid4

import yaml
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from app.api.deps import DbSession
from app.core.config import get_settings
from app.models import Media, ProcessingJob, Workspace
from app.models.defect_review import DefectReview
from app.schemas.survey_result import DefectDecision, SurveyProgress, SurveyResult
from app.services.photo_metadata import (
    apply_coordinate_file,
    locate_from_track,
    photo_metadata,
)
from app.services.survey_import import (
    IMAGE_SUFFIX,
    VIDEO_SUFFIX,
    bind_frames,
    image_or_video_suffix,
    imported_result,
    read_gpx,
)

router = APIRouter(prefix="/surveys", tags=["survey review"])
PIPELINE = "mgts.defects.v1"
settings = get_settings()
MAX_PACKAGE_BYTES = 512 * 1024**2
MAX_SIDECAR_BYTES = 8 * 1024**2


def survey(db, job_id):
    job = db.get(ProcessingJob, job_id)
    if not job or job.pipeline != PIPELINE:
        raise HTTPException(404, "Обследование не найдено")
    return job


def external_survey(db, job_id):
    job = survey(db, job_id)
    if job.parameters.get("inference_mode"):
        raise HTTPException(
            409, "Это обследование обрабатывается встроенным исполнителем"
        )
    return job


def summary(job):
    return {
        "id": job.id,
        "name": job.parameters.get("name"),
        "inference_mode": job.parameters.get("inference_mode"),
        "status": job.status,
        "created_at": job.created_at,
        "progress": 100
        if job.status == "completed"
        else job.parameters.get("progress"),
        "error": job.error_message,
    }


@router.get("")
def list_surveys(db: DbSession):
    jobs = db.scalars(
        select(ProcessingJob)
        .options(defer(ProcessingJob.result))
        .where(ProcessingJob.pipeline == PIPELINE)
        .order_by(ProcessingJob.created_at.desc(), ProcessingJob.id.desc())
    )
    return [summary(job) for job in jobs]


@router.post("", status_code=201)
def import_survey(
    db: DbSession,
    files: Annotated[list[UploadFile], File()],
    name: Annotated[str, Form()] = "Обследование",
    inference_mode: Annotated[Literal["mock", "triton"] | None, Form()] = None,
):
    workspace = db.scalar(select(Workspace).where(Workspace.slug == "mgts"))
    if workspace is None:
        workspace = Workspace(slug="mgts", name="МГТС")
        try:
            with db.begin_nested():
                db.add(workspace)
                db.flush()
        except IntegrityError:
            workspace = db.scalar(select(Workspace).where(Workspace.slug == "mgts"))
    inputs, sidecars, written, seen = [], {}, [], set()
    fixes = []
    media_by_id = {}
    total = 0
    try:
        for upload in files:
            path = PurePosixPath((upload.filename or "").replace("\\", "/"))
            key, suffix = str(path), path.suffix.lower()
            if (
                key in seen
                or ".." in path.parts
                or path.is_absolute()
                or len(key) > 500
            ):
                raise ValueError(f"Повтор или недопустимый путь: {key}")
            seen.add(key)
            if suffix in {".txt", ".yaml", ".yml", ".json"}:
                data = upload.file.read(MAX_SIDECAR_BYTES + 1)
                total += len(data)
                if len(data) > MAX_SIDECAR_BYTES or total > MAX_PACKAGE_BYTES:
                    raise HTTPException(413, "Слишком большой пакет")
                sidecars[key] = data
                continue
            if suffix not in IMAGE_SUFFIX | VIDEO_SUFFIX | {".gpx"}:
                continue
            head = upload.file.read(16)
            upload.file.seek(0)
            if suffix != ".gpx":
                image_or_video_suffix(key, head)
            kind = (
                "image"
                if suffix in IMAGE_SUFFIX
                else "video"
                if suffix in VIDEO_SUFFIX
                else "gps"
            )
            # GPS attachments are served as downloads, never as active XML/HTML.
            dest = settings.upload_dir / (
                uuid4().hex + (".bin" if kind == "gps" else suffix)
            )
            written.append(dest)
            file_size = 0
            with dest.open("xb") as out:
                while chunk := upload.file.read(1024**2):
                    file_size += len(chunk)
                    total += len(chunk)
                    if kind == "gps" and file_size > MAX_SIDECAR_BYTES:
                        raise HTTPException(413, "GPX превышает 8 МиБ")
                    if total > MAX_PACKAGE_BYTES:
                        raise HTTPException(413, "Пакет превышает 512 МиБ")
                    out.write(chunk)
            media = Media(
                id=uuid4(),
                workspace_id=workspace.id,
                kind=kind,
                original_filename=key,
                url="/uploads/" + dest.name,
                source=PIPELINE,
            )
            if kind == "gps":
                fixes.extend(read_gpx(dest))
            db.add(media)
            item = {"id": str(media.id), "name": key, "url": media.url, "kind": kind}
            if kind == "image":
                item.update(photo_metadata(dest))
            media_by_id[item["id"]] = media
            inputs.append(item)
        if not any(i["kind"] in ("image", "video") for i in inputs):
            raise ValueError("Выберите фотографии или видео")
        apply_coordinate_file(inputs, sidecars)
        locate_from_track(inputs, fixes)
        for item in inputs:
            if item["kind"] != "image":
                continue
            media = media_by_id[item["id"]]
            media.latitude, media.longitude = item.get("lat"), item.get("lon")
            if item.get("captured_at"):
                media.captured_at = datetime.fromisoformat(item["captured_at"])
            if "location_source" in item:
                media.attributes = {"location_source": item["location_source"]}
        result = imported_result(inputs, sidecars)
        if inference_mode and (
            result is not None or any(i["kind"] == "video" for i in inputs)
        ):
            raise ValueError(
                "Для покадрового распознавания выберите фотографии без готовой разметки"
            )
        if inference_mode and inference_mode != settings.inference_mode:
            raise HTTPException(409, "Выбранный режим распознавания сейчас недоступен")
        db.flush()
        job_id = uuid4()
        parameters = {"name": name[:255], "inputs": inputs}
        if inference_mode:
            parameters["inference_mode"] = inference_mode
            for item in inputs:
                if item["kind"] == "image":
                    db.add(
                        ProcessingJob(
                            workspace_id=workspace.id,
                            media_id=UUID(item["id"]),
                            pipeline="detection",
                            parameters={"survey_id": str(job_id)},
                        )
                    )
        job = ProcessingJob(
            id=job_id,
            workspace_id=workspace.id,
            pipeline=PIPELINE,
            parameters=parameters,
            status="completed" if result is not None else "queued",
            finished_at=datetime.now(UTC) if result is not None else None,
            result=bind_frames(result, inputs, db, workspace.id)
            if result is not None
            else {},
        )
        db.add(job)
        db.commit()
    except Exception as exc:
        db.rollback()
        for path in written:
            path.unlink(missing_ok=True)
        if isinstance(exc, (ValueError, yaml.YAMLError)):
            raise HTTPException(422, str(exc)[:800]) from exc
        raise
    return summary(job)


@router.get("/inference-config")
def inference_config():
    return {"mode": settings.inference_mode}


@router.get("/map-config")
def map_config():
    return {"browser_key": settings.dgis_browser_key}


@router.get("/{job_id}")
def get_survey(job_id: UUID, db: DbSession):
    job = survey(db, job_id)
    reviews = db.scalars(select(DefectReview).where(DefectReview.job_id == job_id))
    return {
        **summary(job),
        "workspace_id": job.workspace_id,
        "inputs": job.parameters.get("inputs", []),
        "result": job.result,
        "reviews": {
            r.object_id: {"decision": r.decision, "defect": r.defect} for r in reviews
        },
    }


@router.post("/{job_id}/claim")
def claim_survey(job_id: UUID, db: DbSession):
    external_survey(db, job_id)
    changed = db.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job_id, ProcessingJob.status == "queued")
        .values(status="running", started_at=datetime.now(UTC))
    )
    if not changed.rowcount:
        raise HTTPException(409, "Задание уже взято или завершено")
    db.commit()
    return summary(survey(db, job_id))


@router.post("/{job_id}/progress")
def report_progress(job_id: UUID, payload: SurveyProgress, db: DbSession):
    job = external_survey(db, job_id)
    previous = job.parameters.get("progress", 0)
    if payload.percent < previous:
        raise HTTPException(409, "Уже сохранён более поздний этап")
    values = {
        "status": payload.status,
        "parameters": {**job.parameters, "progress": payload.percent},
    }
    if payload.status == "failed":
        values.update(
            error_message=payload.error or "Ошибка обработки",
            finished_at=datetime.now(UTC),
        )
    changed = db.execute(
        update(ProcessingJob)
        .where(
            ProcessingJob.id == job_id,
            ProcessingJob.status == "running",
            func.coalesce(ProcessingJob.parameters["progress"].as_integer(), 0)
            == previous,
        )
        .values(**values)
    )
    if not changed.rowcount:
        raise HTTPException(409, "Состояние задания изменилось")
    db.commit()
    return summary(job)


@router.post("/{job_id}/result")
def submit_result(job_id: UUID, payload: SurveyResult, db: DbSession):
    job = external_survey(db, job_id)
    try:
        result = bind_frames(payload, job.parameters["inputs"], db, job.workspace_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    changed = db.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job_id, ProcessingJob.status != "completed")
        .values(
            status="completed",
            result=result,
            finished_at=datetime.now(UTC),
            error_message=None,
        )
    )
    if not changed.rowcount:
        db.refresh(job)
        if job.result != result:
            raise HTTPException(409, "Результат уже принят")
    db.commit()
    return summary(job)


@router.post("/{job_id}/reviews")
def review_defect(job_id: UUID, payload: DefectDecision, db: DbSession):
    job = survey(db, job_id)
    if not any(
        o["object_id"] == payload.object_id for o in job.result.get("objects", [])
    ):
        raise HTTPException(404, "Объект отсутствует в обследовании")
    db.merge(DefectReview(job_id=job.id, **payload.model_dump()))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Решение изменилось. Обновите карточку.") from exc
    return payload
