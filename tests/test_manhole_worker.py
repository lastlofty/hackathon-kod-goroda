import csv
import json
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.cv.manhole_worker import convert_cards, infer


def image(name="route/sample.jpg"):
    return {"id": str(uuid4()), "name": name, "kind": "image"}


def card(item, status="finding", box=(10, 20, 50, 60)):
    image_id = UUID(item["id"]).hex
    return {
        "image_id": image_id,
        "status": status,
        "bbox_pct": box,
        "p_finding": 0.91 if status == "finding" else None,
        "localization": {"score": 0.8},
        "frames": [{"image_id": image_id, "sign": "open_hatch"}],
    }


def test_imports_states_and_keeps_refusals_as_frames():
    opened, closed, uncertain, poor = [image(f"{i}.jpg") for i in range(4)]
    result = convert_cards(
        [opened, closed, uncertain, poor],
        [card(poor, "rephoto", None), card(uncertain, "uncertain"),
         card(opened), card(closed, "normal")],
    )
    assert [o["verdict"] for o in result["objects"]] == ["defect", "ok", "unknown"]
    assert result["objects"][0]["defects"] == ["open"]
    assert result["frames"][0]["detections"][0]["bbox"] == pytest.approx(
        [0.3, 0.4, 0.4, 0.4]
    )
    assert result["frames"][3]["detections"] == []
    assert result["frames"][3]["analysis_note"]


def test_requires_all_frames_and_valid_geometry():
    item = image()
    with pytest.raises(ValueError, match="не для всех кадров"):
        convert_cards([item], [])
    with pytest.raises(ValueError, match="недопустимую рамку"):
        convert_cards([item], [card(item, box=(0, 0, 120, 60))])


def test_worker_passes_manifest_to_standalone_cli(tmp_path, monkeypatch):
    item = image()
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"sample")
    locator = tmp_path / "locator.json"
    locator.write_text("{}")
    for name, value in {
        "PYTHON": sys.executable, "ROOT": tmp_path,
        "ARTIFACT": tmp_path, "LOCATOR": locator,
    }.items():
        monkeypatch.setenv(f"MANHOLE_INSPECTOR_{name}", str(value))

    def cli(args, *, cwd, check, timeout):
        assert args[1:4] == ["-m", "inspector", "run"]
        assert cwd == tmp_path and check and timeout > 0
        data = Path(args[args.index("--data") + 1])
        with (data / "manifest.csv").open() as stream:
            row, = csv.DictReader(stream)
        assert row["image_id"] == UUID(item["id"]).hex
        assert (data / row["image"]).read_bytes() == source.read_bytes()
        out = Path(args[args.index("--out") + 1])
        out.mkdir()
        (out / "cards.json").write_text(json.dumps([card(item)]))

    monkeypatch.setattr(subprocess, "run", cli)
    progress = []
    result = infer([{**item, "path": source}], progress.append, None)
    assert progress == [5, 95]
    assert result["frames"][0]["media_id"] == item["id"]
    assert result["frames"][0]["frame_id"] == item["name"]
