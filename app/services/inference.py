"""Opt-in execution of an existing queued detection job, with atomic results."""
import logging
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from uuid import UUID

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.cv import adapter
from app.integrations.triton import TritonClient, TritonError
from app.models.finding import Finding
from app.models.job import ProcessingJob
from app.models.media import Media

logger = logging.getLogger(__name__)


def local_image(media: Media, settings: Settings) -> Path:
    # Never fetch user-controlled URLs or permit traversal outside uploads.
    prefix = "/uploads/"
    if not media.url.startswith(prefix):
        raise HTTPException(422, "Inference requires a locally uploaded image")
    filename = media.url[len(prefix):]
    if not filename or Path(filename).name != filename or filename in {".", ".."}:
        raise HTTPException(422, "Invalid uploaded image path")
    root = settings.upload_dir.resolve()
    path = (root / filename).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(422, "Uploaded image is unavailable")
    if path.stat().st_size > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(422, "Uploaded image exceeds size limit")
    return path


def evaluate(path: Path, settings: Settings, parameters: dict) -> list[adapter.Detection]:
    with Image.open(path) as original:
        if original.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError("Unsupported image format")
        if original.width * original.height > 25_000_000:
            raise ValueError("Image pixel limit exceeded")
        image = original.convert("RGB")
    if settings.inference_mode == "mock":
        return adapter.mock_detections(image, parameters)
    # The actual integration point for CV:
    prepared = adapter.preprocess(image, parameters)
    client = TritonClient(settings.triton_url, settings.triton_timeout_seconds)
    outputs = client.infer(settings.triton_model_name, settings.triton_model_version,
                           prepared.inputs, prepared.output_names)
    return adapter.postprocess(outputs, image, prepared, parameters)


def now() -> datetime:
    return datetime.now(timezone.utc)


def run_job(db: Session, job_id: UUID, settings: Settings) -> ProcessingJob:
    if settings.inference_mode == "disabled":
        raise HTTPException(503, "Inference is disabled")
    job = db.get(ProcessingJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status != "queued" or job.pipeline != "detection":
        raise HTTPException(409, "Only queued detection jobs can be run")
    media = db.get(Media, job.media_id) if job.media_id else None
    if media is None or media.workspace_id != job.workspace_id:
        raise HTTPException(422, "Job requires media in its workspace")
    path = local_image(media, settings)
    workspace_id, media_id = job.workspace_id, media.id
    parameters = dict(job.parameters)
    observed_at = media.captured_at
    claim = db.execute(update(ProcessingJob).where(
        ProcessingJob.id == job_id, ProcessingJob.status == "queued",
        ProcessingJob.pipeline == "detection", ProcessingJob.media_id == media_id,
    ).values(status="running", started_at=now(), finished_at=None,
             error_message=None, result={}))
    if claim.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Job has already been claimed or changed")
    db.commit()

    start = monotonic()
    mock = settings.inference_mode == "mock"
    metadata = {"mode": settings.inference_mode,
                "model_name": "mock" if mock else settings.triton_model_name,
                "model_version": "demo" if mock else settings.triton_model_version}
    failure = None
    detections = []
    try:
        detections = [adapter.Detection.model_validate(item) for item in evaluate(path, settings, parameters)]
        if len(detections) > 1000:
            raise ValueError("Too many detections")
    except adapter.AdapterNotConfigured:
        failure = "CV adapter is not configured"
    except TritonError:
        failure = "Triton inference failed"
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        failure = "Invalid image or model output"
    except Exception:
        logger.exception("Inference failed for job %s", job_id)
        failure = "Inference failed"

    # Keep findings and final job state in one transaction. Guard against a
    # concurrent change through the pre-existing generic Jobs API.
    summary = {**metadata, "findings": 0 if failure else len(detections),
               "latency_ms": round((monotonic() - start) * 1000)}
    try:
        finished = db.execute(update(ProcessingJob).where(
            ProcessingJob.id == job_id, ProcessingJob.status == "running",
            ProcessingJob.pipeline == "detection", ProcessingJob.media_id == media_id,
        ).values(status="failed" if failure else "succeeded", finished_at=now(),
                 error_message=failure, result=summary))
        if finished.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "Job changed while running; findings not saved")
        if not failure:
            for detection in detections:
                db.add(Finding(workspace_id=workspace_id, media_id=media_id, job_id=job_id,
                    category=detection.category, label=detection.label, score=detection.score,
                    status="new", geometry=detection.geometry(), severity=detection.severity,
                    recommendation=detection.recommendation,
                    attributes={**detection.attributes, **metadata, "synthetic": mock},
                    source="mock" if mock else "triton", reviewed=False,
                    **({"observed_at": observed_at} if observed_at else {})))
        db.commit()
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Could not persist inference results for job %s", job_id)
        db.execute(update(ProcessingJob).where(ProcessingJob.id == job_id,
                    ProcessingJob.status == "running", ProcessingJob.media_id == media_id,
                    ProcessingJob.pipeline == "detection").values(status="failed", finished_at=now(),
                    error_message="Result persistence failed", result={**metadata, "findings": 0}))
        db.commit()
    db.expire_all()
    result = db.get(ProcessingJob, job_id)
    if result is None:
        raise HTTPException(409, "Job deleted while running")
    return result
