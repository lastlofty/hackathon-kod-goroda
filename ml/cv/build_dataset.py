"""Собирает единый датасет МГТС (ТКШ/РЩ) из двух распакованных частей.

Запуск: python build_dataset.py <часть1/Датасет-ДСС> <часть2/Датасет-ДСС> --out data
Исходные файлы не меняются, в out копируются переименованные изображения + labels.csv.
"""
import argparse
import csv
import hashlib
import re
import shutil
from pathlib import Path

import openpyxl

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# папка-источник -> (тип объекта, группа состояния)
FOLDERS = {
    "Удовлетворительное состояние ТКШ": ("TKSH", "ok"),
    "Удовлетворительное состояние РЩ": ("RSH", "ok"),
    "Неудовлетворительное состояние ЛКП. ТКШ": ("TKSH", "lkp"),
    "Неудовлетворительное состояние ЛКП. РЩ": ("RSH", "lkp"),
    "МП. ТКШ": ("TKSH", "mp"),
    "МП.РЩ": ("RSH", "mp"),
}

FIELDS = [
    "image", "class_dir", "object_type", "condition", "defect_lkp", "defect_mp",
    "mp_deformation", "mp_mount", "mp_door_missing", "severity", "status_raw",
    "description", "mentions_other_object", "source_part", "source_folder",
    "original_name", "sha1", "width", "height",
]


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def read_labels(xlsx):
    wb = openpyxl.load_workbook(xlsx, read_only=True)
    out = {}
    for ws in wb:
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row and row[0] is not None:
                out[str(row[0]).strip().split(".")[0]] = (norm(row[1]), norm(row[2]))
    return out


def derive(obj, group, status, desc):
    text = f"{status} {desc}".lower()
    lkp = int(group == "lkp" or "с повреждени" in text and "лкп" in text)
    mount = int("крепл" in text or "удерживается на" in text or "падение" in text)
    door = int(bool(re.search(r"отсутств\w*\s+дв", text)))
    deform = int("деформ" in text or "разрушение" in text
                 or bool(re.search(r"нарушение целостности(?!\s+узл)", text)))
    mp = int(group == "mp" or mount or door)
    if group != "mp":
        deform = 0
    if mount:
        severity = "critical"
    elif mp or "сквозн" in text or "глубок" in text or re.search(r"отсутс?т\w*\s+лкп", text):
        severity = "high"
    elif lkp:
        severity = "medium"
    else:
        severity = "none"
    other = "РЩ" if obj == "TKSH" else "ТКШ"
    mentions = int(other.lower() in desc.lower())
    return lkp, mp, deform, mount, door, severity, mentions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("parts", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=Path("data"))
    args = ap.parse_args()

    from PIL import Image, ImageOps

    for sub in ("images", "reference"):  # пересборка с нуля: без устаревших файлов
        if (args.out / sub).exists():
            shutil.rmtree(args.out / sub)

    rows, seen_hash, warnings = [], {}, []
    for part_idx, part in enumerate(args.parts, 1):
        for folder in sorted(p for p in part.iterdir() if p.is_dir()):
            if folder.name not in FOLDERS:
                warnings.append(f"неизвестная папка пропущена: {folder}")
                continue
            obj, group = FOLDERS[folder.name]
            class_dir = f"{obj.lower()}_{group}"
            xlsx = next(folder.glob("*.xlsx"), None)
            labels = read_labels(xlsx) if xlsx else {}
            dst_dir = args.out / "images" / class_dir
            dst_dir.mkdir(parents=True, exist_ok=True)
            for img in sorted(folder.iterdir()):
                if img.suffix.lower() not in IMG_EXT:
                    continue
                stem = img.stem
                status, desc = labels.get(stem, ("", ""))
                if stem not in labels:
                    warnings.append(f"нет строки в xlsx: {img}")
                sha1 = hashlib.sha1(img.read_bytes()).hexdigest()
                if sha1 in seen_hash:
                    warnings.append(f"дубликат {img} == {seen_hash[sha1]}")
                    continue
                seen_hash[sha1] = str(img)
                name = f"{class_dir}_{stem}{img.suffix.lower().replace('.jpeg', '.jpg')}"
                if (dst_dir / name).exists():
                    raise SystemExit(f"коллизия имён: {dst_dir / name} ({img})")
                shutil.copy2(img, dst_dir / name)
                with Image.open(img) as im:
                    w, h = ImageOps.exif_transpose(im).size  # размер с учётом EXIF-поворота
                lkp, mp, deform, mount, door, sev, mentions = derive(obj, group, status, desc)
                rows.append({
                    "image": f"images/{class_dir}/{name}", "class_dir": class_dir,
                    "object_type": obj, "condition": "ok" if group == "ok" else "defect",
                    "defect_lkp": lkp, "defect_mp": mp, "mp_deformation": deform,
                    "mp_mount": mount, "mp_door_missing": door, "severity": sev,
                    "status_raw": status, "description": desc,
                    "mentions_other_object": mentions, "source_part": part_idx,
                    "source_folder": folder.name, "original_name": img.name,
                    "sha1": sha1, "width": w, "height": h,
                })
            for stem in labels:
                if not any(r["original_name"].split(".")[0] == stem and r["source_folder"] == folder.name for r in rows):
                    warnings.append(f"строка xlsx без файла: {folder.name}/{stem}")
        for ref in part.iterdir():
            if ref.is_file() and ref.suffix.lower() in IMG_EXT:
                (args.out / "reference").mkdir(parents=True, exist_ok=True)
                shutil.copy2(ref, args.out / "reference" / ref.name)
            elif ref.is_file() and ref.suffix.lower() == ".txt":
                shutil.copy2(ref, args.out / "abbreviations.txt")

    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "labels.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, FIELDS)
        wr.writeheader()
        wr.writerows(rows)
    (args.out / "warnings.txt").write_text("".join(w + "\n" for w in warnings), encoding="utf-8")

    from collections import Counter
    print(f"изображений: {len(rows)}")
    for k, v in sorted(Counter(r["class_dir"] for r in rows).items()):
        print(f"  {k}: {v}")
    print("severity:", dict(Counter(r["severity"] for r in rows)))
    for w in warnings:
        print("!", w)


if __name__ == "__main__":
    main()
