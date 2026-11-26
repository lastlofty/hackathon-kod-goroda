"""Build a local image-level dataset from the original MGTS ZIP archives."""
import argparse
import csv
import hashlib
import io
import json
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
import zipfile

from openpyxl import load_workbook
from PIL import Image

CATEGORIES = {
    "МП.РЩ": ("rsh", "mechanical_damage"),
    "МП. ТКШ": ("tksh", "mechanical_damage"),
    "Неудовлетворительное состояние ЛКП. РЩ": ("rsh", "coating_damage"),
    "Неудовлетворительное состояние ЛКП. ТКШ": ("tksh", "coating_damage"),
    "Удовлетворительное состояние РЩ": ("rsh", "normal"),
    "Удовлетворительное состояние ТКШ": ("tksh", "normal"),
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def image_key(value):
    if value is None:
        raise ValueError("Empty image name in Excel")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    path = PurePosixPath(text)
    return (path.stem if path.suffix.lower() in IMAGE_SUFFIXES else text).casefold()


def prepare(archives, out):
    out = Path(out).resolve()
    if out.exists():
        raise ValueError(f"Output already exists; choose a new directory: {out}")
    rows, payloads, sources = [], {}, []
    seen_paths, used_ids = set(), set()
    for archive in sorted(map(Path, archives), key=lambda p: p.name):
        archive_hash = sha(archive.read_bytes())
        if any(s["sha256"] == archive_hash for s in sources):
            raise ValueError(f"Duplicate archive: {archive.name}")
        sources.append({"name": archive.name, "sha256": archive_hash})
        with zipfile.ZipFile(archive) as z:
            names = [x.filename for x in z.infolist() if not x.is_dir()]
            if len(names) != len(set(names)):
                raise ValueError(f"Duplicate ZIP member: {archive.name}")
            images = defaultdict(dict)
            for n in names:
                p = PurePosixPath(n)
                if p.is_absolute() or ".." in p.parts or "\\" in n:
                    raise ValueError(f"Unsafe ZIP member: {n}")
                if p.suffix.lower() not in IMAGE_SUFFIXES:
                    continue
                key = image_key(p.name)
                if key in images[p.parent]:
                    raise ValueError(f"Ambiguous image stem in {p.parent}: {key}")
                images[p.parent][key] = n
            labels = {}
            for n in sorted(names):
                p = PurePosixPath(n)
                if p.suffix.lower() != ".xlsx":
                    continue
                if p.parent.name not in CATEGORIES:
                    raise ValueError(f"Unknown label folder: {p.parent}")
                book = load_workbook(io.BytesIO(z.read(n)), read_only=True, data_only=True)
                try:
                    for sheet in book:
                        it = sheet.iter_rows(values_only=True)
                        header = next(it, ())
                        if tuple(header[:3]) != ("Имя файла", "Статус", "Описание"):
                            raise ValueError(f"Unexpected Excel header: {n} / {sheet.title}")
                        for number, values in enumerate(it, 2):
                            if all(v is None for v in values):
                                continue
                            key = image_key(values[0])
                            member = images[p.parent].get(key)
                            if member is None:
                                raise ValueError(f"Missing image: {n}:{number} ({key})")
                            if member in labels:
                                raise ValueError(f"Duplicate annotation: {member}")
                            if len(values) < 3 or not values[1] or not values[2]:
                                raise ValueError(f"Incomplete annotation: {n}:{number}")
                            labels[member] = (n, sheet.title, number, str(values[1]), str(values[2]))
                finally:
                    book.close()
            for directory in sorted(images, key=str):
                for member in sorted(images[directory].values()):
                    if member in seen_paths:
                        raise ValueError(f"Repeated source path across archives: {member}")
                    seen_paths.add(member)
                    raw = z.read(member)
                    digest = sha(raw)
                    image_id = "mgts_" + sha(member.encode("utf-8") + b"\0" + raw)[:20]
                    if image_id in used_ids:
                        raise ValueError(f"Duplicate image ID: {image_id}")
                    used_ids.add(image_id)
                    with Image.open(io.BytesIO(raw)) as im:
                        im.verify()
                    with Image.open(io.BytesIO(raw)) as im:
                        im.load()
                        width, height = im.size
                        fmt = im.format
                        orientation = im.getexif().get(274, 1)
                    suffix = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(fmt)
                    if suffix is None:
                        raise ValueError(f"Unsupported image format: {member}: {fmt}")
                    target = f"images/{image_id}{suffix}"
                    label = labels.get(member)
                    obj, category = CATEGORIES[directory.name] if label else (None, None)
                    row = {
                        "image_id": image_id, "image_path": target,
                        "source_archive": archive.name, "source_path": member,
                        "sha256": digest, "width": width, "height": height,
                        "format": fmt, "exif_orientation": orientation,
                        "object_type": obj, "condition_category": category,
                        "condition_binary": ("normal" if category == "normal" else "damaged") if label else None,
                        "status_raw": label[3] if label else None,
                        "description_raw": label[4] if label else None,
                        "annotation_file": label[0] if label else None,
                        "annotation_sheet": label[1] if label else None,
                        "annotation_row": label[2] if label else None,
                        "annotation_level": "image" if label else None,
                        "asset_group_id": None, "bbox": None, "latitude": None, "longitude": None,
                    }
                    rows.append(row)
                    payloads[target] = raw
    if not rows:
        raise ValueError("No images found")
    rows.sort(key=lambda row: row["image_id"])
    hashes = defaultdict(list)
    stems = defaultdict(list)
    for row in rows:
        hashes[row["sha256"]].append(row["image_id"])
        stems[PurePosixPath(row["source_path"]).name.casefold()].append(row["image_id"])
    counts = Counter(f'{r["object_type"]}/{r["condition_category"]}' for r in rows if r["annotation_level"])
    summary = {
        "schema_version": 1, "archives": sources, "images": len(rows),
        "annotated": sum(r["annotation_level"] is not None for r in rows),
        "unannotated": [r["image_id"] for r in rows if not r["annotation_level"]],
        "category_counts": dict(sorted(counts.items())),
        "exact_duplicate_groups": [v for v in hashes.values() if len(v) > 1],
        "repeated_filenames": {k: v for k, v in stems.items() if len(v) > 1},
        "split_status": "not_created_pending_asset_group_review",
    }
    # Do not extract arbitrary ZIP paths or overwrite previous results.
    out.mkdir(parents=True, exist_ok=False)
    (out / "images").mkdir()
    for target, raw in payloads.items():
        (out / target).write_bytes(raw)
    for name, obj in [("manifest.json", rows), ("validation.json", summary)]:
        (out / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (out / "asset_review.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["image_id", "image_path", "source_path", "object_type", "condition_category", "asset_group_id", "review_notes"]
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.archives, args.out), ensure_ascii=False, indent=2))
