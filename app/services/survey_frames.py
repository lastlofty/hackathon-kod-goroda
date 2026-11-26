"""Detach media from an inspection without modifying another inspection's originals."""

from sqlalchemy import select

from app.models.defect_review import RemovedSurveyFrame


def removed_media_ids(db, job_id):
    return {
        str(media_id)
        for media_id in db.scalars(
            select(RemovedSurveyFrame.media_id).where(
                RemovedSurveyFrame.job_id == job_id
            )
        )
    }


def remaining_result(result, removed):
    if not result or not removed:
        return result
    frames = [f for f in result["frames"] if f["media_id"] not in removed]
    if len(frames) == len(result["frames"]):
        return result
    detections = {d["det_id"]: d for f in frames for d in f["detections"]}

    def rank(det_id):
        d = detections[det_id]
        return tuple(
            d[k] if d.get(k) is not None else -1 for k in ("defect_score", "score")
        )

    objects = []
    for obj in result["objects"]:
        observations = [i for i in obj["observations"] if i in detections]
        if observations:
            best = obj["best_det_id"]
            if best not in observations:
                best = max(observations, key=rank)
            objects.append({**obj, "observations": observations, "best_det_id": best})
    return {**result, "frames": frames, "objects": objects}
