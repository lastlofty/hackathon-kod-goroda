"""Run the repository's single-image detection jobs for an uploaded survey."""

import logging
from datetime import UTC, datetime, timedelta
from threading import Event

from fastapi import HTTPException
from sqlalchemy import func, select, update

from app.db.session import SessionLocal
from app.models import Finding, ProcessingJob
from app.schemas.survey_result import SurveyResult
from app.services.inference import run_job
from app.services.survey_import import bind_frames

logger = logging.getLogger(__name__)
ACTIVE = ("queued", "running")


def survey_result(db, survey, jobs):
    inputs = survey.parameters["inputs"]
    frames = {
        item["id"]: {"frame_id": item["name"], "media_id": item["id"], "detections": []}
        for item in inputs
        if item["kind"] == "image"
    }
    objects, ranks = {}, {}
    findings = db.scalars(
        select(Finding)
        .where(
            Finding.job_id.in_([job.id for job in jobs]),
            Finding.workspace_id == survey.workspace_id,
        )
        .order_by(Finding.observed_at, Finding.id)
    )
    for finding in findings:
        attributes = finding.attributes or {}
        det_id = str(finding.id)
        object_id = str(attributes.get("object_id") or finding.entity_id or det_id)
        box = finding.geometry
        x, y, w, h = (box[key] for key in ("x", "y", "width", "height"))
        defect = attributes.get("defect")
        defect_score = attributes.get("defect_score")
        frames[str(finding.media_id)]["detections"].append(
            {
                "det_id": det_id,
                "object_id": object_id,
                "class": finding.category,
                "bbox": [x + w / 2, y + h / 2, w, h],
                "score": finding.score,
                "inference": {
                    "model_name": attributes.get("model_name"),
                    "model_version": attributes.get("model_version"),
                    "label": finding.label,
                    "severity": finding.severity,
                    "recommendation": finding.recommendation,
                },
                "defect": defect,
                "defect_score": defect_score,
            }
        )
        obj = objects.setdefault(
            object_id, {"object_id": object_id, "observations": []}
        )
        obj["observations"].append(det_id)
        rank = (
            defect_score if defect_score is not None else -1,
            finding.score if finding.score is not None else -1,
        )
        if object_id not in ranks or rank > ranks[object_id]:
            ranks[object_id] = rank
            obj.update(
                {
                    "class": finding.category,
                    "best_det_id": det_id,
                    "status": attributes.get("priority") or "review",
                    "verdict": attributes.get("verdict"),
                    "defect": defect,
                    "defect_score": defect_score,
                    "priority_level": attributes.get("priority_level"),
                    "defects": attributes.get("defects") or [],
                    "severity": attributes.get("severity"),
                    "recommendation": finding.recommendation,
                }
            )
    result = SurveyResult.model_validate(
        {"frames": list(frames.values()), "objects": list(objects.values())}
    )
    return bind_frames(result, inputs, db, survey.workspace_id)


def fail(db, survey, message):
    db.execute(
        update(ProcessingJob)
        .where(
            ProcessingJob.id == survey.id,
            ProcessingJob.status.in_(ACTIVE),
        )
        .values(
            status="failed",
            error_message=str(message)[:2048],
            finished_at=datetime.now(UTC),
        )
    )
    db.commit()


def advance(db, survey, settings):
    """Advance one image. Each child job atomically claims and persists its findings."""
    jobs = list(
        db.scalars(
            select(ProcessingJob)
            .where(
                ProcessingJob.workspace_id == survey.workspace_id,
                ProcessingJob.pipeline == "detection",
                ProcessingJob.parameters["survey_id"].as_string() == str(survey.id),
            )
            .order_by(ProcessingJob.created_at, ProcessingJob.id)
        )
    )
    expected = sum(item["kind"] == "image" for item in survey.parameters["inputs"])
    if not jobs or len(jobs) != expected:
        fail(db, survey, "Задания фотографий недоступны")
        return True
    for job in jobs:
        if job.status == "failed":
            fail(db, survey, job.error_message or "Обработка фотографии не завершилась")
            return True
        if job.status == "running" and job.started_at:
            # A killed executor cannot return a result. The run_job state guard
            # prevents a late response from writing over a terminal decision.
            deadline = datetime.now(UTC) - timedelta(minutes=30)
            if job.started_at.replace(tzinfo=UTC) < deadline:
                db.execute(
                    update(ProcessingJob)
                    .where(
                        ProcessingJob.id == job.id,
                        ProcessingJob.status == "running",
                    )
                    .values(
                        status="failed",
                        finished_at=datetime.now(UTC),
                        error_message="Истекло время обработки фотографии",
                    )
                )
                db.commit()
                return True
    if survey.status == "queued":
        db.execute(
            update(ProcessingJob)
            .where(
                ProcessingJob.id == survey.id,
                ProcessingJob.status == "queued",
            )
            .values(status="running", started_at=datetime.now(UTC))
        )
        db.commit()
    pending = next((j for j in jobs if j.status == "queued"), None)
    complete = sum(j.status == "succeeded" for j in jobs)
    if complete == len(jobs):
        result = survey_result(db, survey, jobs)
        db.execute(
            update(ProcessingJob)
            .where(
                ProcessingJob.id == survey.id,
                ProcessingJob.status == "running",
            )
            .values(status="completed", result=result, finished_at=datetime.now(UTC))
        )
        db.commit()
        return True
    percent = 100 * complete // len(jobs)
    if percent > survey.parameters.get("progress", 0):
        db.execute(
            update(ProcessingJob)
            .where(
                ProcessingJob.id == survey.id,
                ProcessingJob.status == "running",
                func.coalesce(ProcessingJob.parameters["progress"].as_integer(), 0)
                < percent,
            )
            .values(parameters={**survey.parameters, "progress": percent})
        )
        db.commit()
    if pending is None:
        return False
    try:
        run_job(db, pending.id, settings)
    except HTTPException as exc:
        db.rollback()
        if exc.status_code != 409:
            fail(db, survey, exc.detail)
    return True


def run_queue(settings, stop: Event):
    while not stop.is_set():
        try:
            with SessionLocal() as db:
                surveys = db.scalars(
                    select(ProcessingJob)
                    .where(
                        ProcessingJob.pipeline == "mgts.defects.v1",
                        ProcessingJob.status.in_(ACTIVE),
                        ProcessingJob.parameters["inference_mode"].as_string()
                        == settings.inference_mode,
                    )
                    .order_by(ProcessingJob.created_at, ProcessingJob.id)
                )
                worked = False
                for survey in surveys:
                    try:
                        if advance(db, survey, settings):
                            worked = True
                            break
                    except (KeyError, TypeError, ValueError):
                        db.rollback()
                        logger.exception(
                            "Invalid detection result for survey %s", survey.id
                        )
                        fail(
                            db,
                            survey,
                            "Ответ модели не соответствует формату обследования",
                        )
                        worked = True
                        break
            if not worked:
                stop.wait(1)
        except Exception:
            logger.exception("Could not advance the survey inference queue")
            stop.wait(2)
