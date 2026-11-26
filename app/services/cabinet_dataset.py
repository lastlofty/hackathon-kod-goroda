"""Read the three-column photo inventory supplied with the DSS cabinet archives."""

import re
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from app.schemas.survey_result import SurveyResult

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def worksheet_rows(data):
    def xml(book, name):
        entry = book.getinfo(name)
        if entry.file_size > 4 * 1024**2:
            raise ValueError("Слишком большой лист XLSX")
        contents = book.read(entry)
        if b"<!DOCTYPE" in contents.upper() or b"\x00" in contents:
            raise ValueError("Неподдерживаемый XML таблицы")
        return ET.fromstring(contents)

    def text(node):
        return "".join(part.text or "" for part in node.iter(NS + "t"))

    try:
        with ZipFile(BytesIO(data)) as workbook:
            shared = (
                [text(si) for si in xml(workbook, "xl/sharedStrings.xml")]
                if "xl/sharedStrings.xml" in workbook.namelist()
                else []
            )
            sheet = xml(workbook, "xl/worksheets/sheet1.xml")
            for row in sheet.findall(f".//{NS}sheetData/{NS}row"):
                cells = {}
                for cell in row.findall(NS + "c"):
                    column = cell.get("r", "").rstrip("0123456789")
                    value = cell.findtext(NS + "v", "")
                    if cell.get("t") == "s":
                        value = shared[int(value)]
                    elif cell.get("t") == "inlineStr":
                        value = text(cell)
                    cells[column] = value.strip()
                values = tuple(cells.get(c, "") for c in "ABC")
                if any(values):
                    yield values
    except (BadZipFile, ET.ParseError, IndexError, KeyError, RuntimeError) as exc:
        raise ValueError("Не удалось прочитать таблицу XLSX") from exc


def classify(status, description):
    status = status.casefold()
    details = description.casefold()
    if status.startswith("удовлет") and "отсутствуют" in details:
        return [], "ok"
    defects = []
    if ("лкп" in status and "без повреждения" not in status) or "коррози" in details:
        defects.append("повреждение ЛКП")
    if "деформац" in status:
        defects.append("деформация")
    if "креплен" in status or "удерживается на питающем" in details:
        defects.append("нарушение крепления")
    if re.search(r"отсутств\w*\s+двер", details) or "отсутствие двери" in status:
        defects.append("отсутствие двери")
    return defects, "defect" if defects else "unknown"


def cabinet_result(inputs, sheets):
    images = [i["name"] for i in inputs if i["kind"] == "image"]
    index = {}
    frames = {
        name: {"frame_id": name, "lat": None, "lon": None, "detections": []}
        for name in images
    }
    for name in images:
        path = PurePosixPath(name)
        key = path.parent, path.stem
        index[key] = name if key not in index else None
    objects = []
    for name, data in sheets.items():
        folder = PurePosixPath(name).parent
        rows = worksheet_rows(data)
        if next(rows, None) != ("Имя файла", "Статус", "Описание"):
            raise ValueError(
                f"В {name} ожидаются колонки «Имя файла», «Статус», «Описание»"
            )
        classes = set(re.findall(r"\b(?:ТКШ|РЩ)\b", folder.name.upper()))
        if len(classes) != 1:
            raise ValueError(f"Укажите ТКШ или РЩ в названии папки {folder}")
        category = classes.pop()
        for filename, status, description in rows:
            path = index.get((folder, PurePosixPath(filename).stem))
            if not path or frames[path]["detections"]:
                raise ValueError(
                    f"Неоднозначная или отсутствующая фотография {folder}/{filename}"
                )
            defects, verdict = classify(status, description)
            # The inventory identifies a cabinet on a photo, without cross-photo identities or boxes.
            det_id = path + "#1"
            frames[path]["detections"].append(
                {
                    "det_id": det_id,
                    "object_id": path,
                    "class": category,
                    "bbox": None,
                    "defects": defects,
                }
            )
            objects.append(
                {
                    "object_id": path,
                    "class": category,
                    "lat": None,
                    "lon": None,
                    "description": description,
                    "defects": defects,
                    "verdict": verdict,
                    "status": "normal" if verdict == "ok" else "review",
                    "observations": [det_id],
                    "best_det_id": det_id,
                }
            )
    return SurveyResult.model_validate(
        {"source": "dataset", "frames": list(frames.values()), "objects": objects}
    )
