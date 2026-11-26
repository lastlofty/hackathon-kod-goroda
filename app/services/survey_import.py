import json
from datetime import datetime
from pathlib import PurePosixPath
from uuid import UUID
from xml.etree import ElementTree

import yaml

from app.models import Media
from app.schemas.survey_result import SurveyResult
from app.services.cabinet_dataset import cabinet_result, prepared_result
from app.services.photo_metadata import image_path_index

IMAGE_SUFFIX = {".jpg", ".jpeg", ".webp", ".png"}
VIDEO_SUFFIX = {".mp4", ".mov", ".webm"}


def image_or_video_suffix(name, head):
    suffix = PurePosixPath(name).suffix.lower()
    valid = {
        ".jpg": head.startswith(b"\xff\xd8\xff"),
        ".jpeg": head.startswith(b"\xff\xd8\xff"),
        ".png": head.startswith(b"\x89PNG\r\n\x1a\n"),
        ".webp": head[:4] == b"RIFF" and head[8:12] == b"WEBP",
        ".mp4": head[4:8] == b"ftyp",
        ".mov": head[4:8] in (b"ftyp", b"moov", b"mdat", b"wide"),
        ".webm": head.startswith(b"\x1aE\xdf\xa3"),
    }
    if suffix in IMAGE_SUFFIX and valid[".webp"]:
        return ".webp"
    if not valid.get(suffix):
        raise ValueError(f"Неподдерживаемое содержимое файла {name}")
    return suffix


def read_gpx(path):
    if path.stat().st_size > 8 * 1024**2:
        raise ValueError("GPX превышает 8 МБ")
    data = path.read_bytes()
    if b"<!DOCTYPE" in data.upper() or b"\x00" in data:
        raise ValueError("Неподдерживаемый формат GPX")
    try:
        root = ElementTree.fromstring(data)
        if root.tag.split("}")[-1] != "gpx":
            raise ValueError("Ожидается GPS-трек в формате GPX")
        has_points = False
        fixes = []
        for parent in root.iter():
            tag = parent.tag.split("}")[-1]
            if tag not in ("trkseg", "rte"):
                continue
            for point in parent:
                if point.tag.split("}")[-1] != (
                    "trkpt" if tag == "trkseg" else "rtept"
                ):
                    continue
                lat, lon = float(point.attrib["lat"]), float(point.attrib["lon"])
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValueError("Координаты GPX вне диапазона")
                has_points = True
                stamp = point.findtext("{*}time")
                if stamp:
                    captured = datetime.fromisoformat(stamp.strip())
                    if captured.tzinfo is not None:
                        fixes.append((captured.timestamp(), lat, lon))
        if not has_points:
            raise ValueError("Нет точек маршрута в GPX")
        return fixes
    except (ElementTree.ParseError, KeyError) as exc:
        raise ValueError("Повреждённый GPX-трек") from exc


def yolo_key(path, folder):
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if folder in parts[:-1]:
        del parts[parts.index(folder)]
    return tuple(parts)


def imported_result(inputs, sidecars, digests):
    manifests = [p for p in sidecars if p.lower().endswith(".json")]
    for name in manifests:
        if PurePosixPath(name).name == "manifest.json":
            contents = json.loads(sidecars[name])
            if isinstance(contents, list):
                if len(manifests) != 1:
                    raise ValueError("Выберите один датасет или один результат модели")
                return prepared_result(inputs, name, contents, digests)
    if manifests:
        if len(manifests) != 1:
            raise ValueError("Для одной загрузки нужен один JSON результата")
        return SurveyResult.model_validate_json(sidecars[manifests[0]])
    sheets = {p: data for p, data in sidecars.items() if p.lower().endswith(".xlsx")}
    if sheets:
        return cabinet_result(inputs, sheets)
    configs = [p for p in sidecars if p.lower().endswith((".yaml", ".yml"))]
    labels = {}
    for path, data in sidecars.items():
        file = PurePosixPath(path)
        if file.suffix.lower() != ".txt":
            continue
        if "labels" not in file.parts and file.stem.lower() in {
            "train",
            "val",
            "test",
            "readme",
            "classes",
        }:
            continue
        key = yolo_key(path, "labels")
        if key in labels:
            raise ValueError(f"Неоднозначные метки для {path}")
        labels[key] = (path, data)
    if not configs and not labels:
        return None
    if len(configs) > 1:
        raise ValueError("Нужен один YAML со списком классов")
    config = yaml.safe_load(sidecars[configs[0]]) if configs else {}
    names = config.get("names", {}) if isinstance(config, dict) else {}
    frames, objects = [], []
    for item in inputs:
        if item["kind"] != "image":
            continue
        path = item["name"]
        label_path, content = labels.pop(yolo_key(path, "images"), ("", b""))
        detections = []
        for line_no, line in enumerate(content.decode("utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            try:
                cls, x, y, w, h = line.split()
                idx = int(cls)
                if idx < 0:
                    raise ValueError()
                label = (
                    names[idx]
                    if isinstance(names, list)
                    else names.get(idx, names.get(cls, cls))
                )
                bbox = list(map(float, [x, y, w, h]))
            except (TypeError, ValueError, IndexError, AttributeError) as exc:
                raise ValueError(
                    f"{label_path}, строка {line_no}: ожидается class cx cy width height"
                ) from exc
            det_id = f"{path}#{line_no}"
            detections.append(
                {
                    "det_id": det_id,
                    "object_id": det_id,
                    "class": str(label),
                    "bbox": bbox,
                }
            )
            objects.append(
                {
                    "object_id": det_id,
                    "class": str(label),
                    "status": "review",
                    "observations": [det_id],
                    "best_det_id": det_id,
                }
            )
        frames.append({"frame_id": path, "detections": detections})
    if labels:
        raise ValueError(f"Нет изображения для {next(iter(labels.values()))[0]}")
    return SurveyResult.model_validate({"frames": frames, "objects": objects})


def bind_frames(result, inputs, db, workspace_id):
    index = image_path_index(inputs)
    by_id = {i["id"]: i for i in inputs if i["kind"] == "image"}
    remaining = {i["id"]: i["name"] for i in by_id.values()}
    bound_ids = set()
    payload = result.model_dump(mode="json", by_alias=True)
    for obj in payload["objects"]:
        if obj["verdict"] is None:
            del obj["verdict"]
        if obj["recommendation"] is None:
            del obj["recommendation"]
    for frame in payload["frames"]:
        for detection in frame["detections"]:
            if detection["inference"] is None:
                del detection["inference"]
        name = frame["frame_id"]
        item = index.get(name)
        if frame["media_id"]:
            if item and frame["media_id"] != item["id"]:
                raise ValueError(f"media_id не совпадает с исходным кадром {name}")
            media = db.get(Media, UUID(frame["media_id"]))
            if (
                not media
                or media.workspace_id != workspace_id
                or media.kind != "image"
                or not media.url.startswith("/uploads/")
            ):
                raise ValueError(f"Нет доступного изображения для {name}")
            frame["url"] = media.url
        elif item:
            frame["media_id"], frame["url"] = item["id"], item["url"]
        else:
            raise ValueError(f"Загрузите изображение {name} или укажите его media_id")
        if frame["media_id"] in bound_ids:
            raise ValueError(f"Фото уже связано с другим кадром: {name}")
        bound_ids.add(frame["media_id"])
        source = by_id.get(frame["media_id"], {})
        if source.get("lat") is not None and source.get("lon") is not None:
            frame["lat"], frame["lon"] = source["lat"], source["lon"]
        if frame.get("captured_at") is None and "captured_at" in source:
            frame["captured_at"] = source["captured_at"]
        remaining.pop(frame["media_id"], None)
    if remaining:
        raise ValueError(
            "Нет результата для исходного кадра " + next(iter(remaining.values()))
        )
    return payload
