"""Bridge the standalone route-inspector v0.1.0 CLI to the survey API."""

import csv
import json
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from app.schemas.survey_result import SurveyResult

MODEL_NAME = "mgts-route-inspector / YOLO26n + DINOv2"
MODEL_VERSION = "v0.1.0"
RETAKE = "Модель не смогла оценить кадр. Нужен другой снимок или ручная проверка."


def normalized_box(box_pct):
    x1, y1, x2, y2 = (value / 100 for value in box_pct)
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise ValueError("Route Inspector вернул недопустимую рамку")
    return [(x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1]


def convert_cards(images, cards):
    expected_ids = {UUID(item["id"]).hex for item in images}
    by_id = {}
    for card in cards:
        image_id = card["image_id"]
        if image_id not in expected_ids or image_id in by_id:
            raise ValueError("Route Inspector вернул неизвестный или повторный кадр")
        by_id[image_id] = card
    if by_id.keys() != expected_ids:
        raise ValueError("Route Inspector вернул результат не для всех кадров")

    frames, objects = [], []
    for item in images:
        image_id = UUID(item["id"]).hex
        card = by_id[image_id]
        state = card["status"]
        frame = {"frame_id": item["name"], "media_id": item["id"], "detections": []}
        frames.append(frame)

        evidence, = card["frames"]
        if evidence["image_id"] != image_id:
            raise ValueError("Route Inspector вернул несовместимую привязку кадра")
        if state not in {"normal", "finding", "uncertain", "rephoto"}:
            raise ValueError("Route Inspector вернул неизвестное состояние")
        if state == "rephoto" or card["bbox_pct"] is None:
            frame["analysis_note"] = RETAKE
            continue

        if state == "normal":
            verdict, priority, defects = "ok", "normal", []
            recommendation = "По этому кадру дополнительных действий не требуется."
        elif state == "finding" and evidence.get("sign") == "open_hatch":
            verdict, priority, defects = "defect", "urgent", ["open"]
            recommendation = "Передать на срочную проверку открытого колодца."
        else:
            verdict, priority, defects = "unknown", "review", []
            recommendation = "Проверить состояние крышки вручную."

        det_id, object_id = f"{image_id}:1", f"manhole:{image_id}"
        score = card.get("p_finding")
        frame["detections"].append({
            "det_id": det_id,
            "object_id": object_id,
            "class": "manhole",
            "bbox": normalized_box(card["bbox_pct"]),
            "score": (card.get("localization") or {}).get("score"),
            "defects": defects,
            "defect_score": score,
            "inference": {"model_name": MODEL_NAME, "model_version": MODEL_VERSION},
        })
        objects.append({
            "object_id": object_id,
            "class": "manhole",
            "verdict": verdict,
            "status": priority,
            "defects": defects,
            "defect_score": score,
            "recommendation": recommendation,
            "observations": [det_id],
            "best_det_id": det_id,
        })
    return SurveyResult.model_validate({"frames": frames, "objects": objects}).model_dump(
        mode="json", by_alias=True, exclude_none=True,
    )


def required_path(variable, *, directory=False, executable=False):
    value = os.getenv(variable)
    if not value:
        raise ValueError(f"Задайте {variable} для Route Inspector")
    # Preserve the venv executable path: resolving a symlink can select system Python.
    path = Path(value).expanduser().absolute()
    exists = path.is_dir() if directory else path.is_file()
    if not exists or (executable and not os.access(path, os.X_OK)):
        raise ValueError(f"{variable} не указывает на доступный путь")
    return path


def infer(inputs, progress, _publish_frame):
    images = [item for item in inputs if item["kind"] == "image"]
    if not images or any(item["kind"] == "video" for item in inputs):
        raise ValueError("Пилотный адаптер Route Inspector принимает только фотографии")
    python = required_path("MANHOLE_INSPECTOR_PYTHON", executable=True)
    root = required_path("MANHOLE_INSPECTOR_ROOT", directory=True)
    artifact = required_path("MANHOLE_INSPECTOR_ARTIFACT", directory=True)
    locator = required_path("MANHOLE_INSPECTOR_LOCATOR")
    with TemporaryDirectory(prefix="manhole-inspector-") as work:
        data, out = Path(work) / "input", Path(work) / "output"
        data.mkdir()
        with (data / "manifest.csv").open("w", encoding="utf-8", newline="") as stream:
            manifest = csv.writer(stream)
            manifest.writerow(["image", "image_id", "asset_id", "object_type"])
            for item in images:
                image_id = UUID(item["id"]).hex
                source = Path(item["path"])
                filename = image_id + source.suffix
                shutil.copyfile(source, data / filename)
                manifest.writerow([filename, image_id, image_id, "well"])
        progress(5)
        try:
            subprocess.run(
                [str(python), "-m", "inspector", "run", "--data", str(data),
                 "--artifact", str(artifact), "--locator", str(locator),
                 "--out", str(out), "--json"],
                cwd=root, check=True, timeout=900,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise RuntimeError("Не удалось выполнить распознавание Route Inspector") from exc
        with (out / "cards.json").open(encoding="utf-8") as stream:
            result = convert_cards(images, json.load(stream))
        progress(95)
        return result
