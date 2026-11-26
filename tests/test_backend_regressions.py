import json
from io import BytesIO

import pytest
from PIL import Image

from app.api import surveys


def jpeg_image():
    with BytesIO() as buffer:
        Image.new("RGB", (1, 1)).save(buffer, format="JPEG")
        return buffer.getvalue()


@pytest.mark.parametrize(
    "collection, fields, extra",
    [
        ("workspaces", ("slug", "name", "settings"), {}),
        ("entity-types", ("code", "name", "attribute_schema", "active"),
         {"code": "pole", "name": "Pole"}),
        ("entities", ("attributes",), {}),
        ("media", ("kind", "url", "attributes"), {"url": "https://example.com/photo.jpg"}),
        ("jobs", ("pipeline", "status", "parameters", "result"), {"pipeline": "demo"}),
        ("findings", ("observed_at", "category", "attributes", "reviewed"), {"category": "pole"}),
    ],
)
def test_patch_rejects_null_without_changing_record(client, collection, fields, extra):
    workspace = client.post("/api/v1/workspaces", json={"slug": "demo", "name": "Demo"})
    assert workspace.status_code == 201
    body = {"workspace_id": workspace.json()["id"], **extra}
    created = workspace if collection == "workspaces" else client.post(
        f"/api/v1/{collection}", json=body
    )
    assert created.status_code == 201
    before = created.json()
    url = f"/api/v1/{collection}/{before['id']}"
    for field in fields:
        assert client.patch(url, json={field: None}).status_code == 422
    assert client.get(url).json() == before


def test_survey_preserves_source_frame_location(client, monkeypatch, tmp_path):
    monkeypatch.setattr(surveys.settings, "upload_dir", tmp_path)
    coordinates = {"frames": [{"frame_id": "photo.jpg", "lat": 55, "lon": 37}]}
    result = {
        "frames": [{"frame_id": "photo.jpg", "lat": 56, "lon": 38, "detections": []}],
        "objects": [],
    }
    created = client.post(
        "/api/v1/surveys",
        files=[
            ("files", ("photo.jpg", jpeg_image(), "image/jpeg")),
            ("files", ("coordinates.json", json.dumps(coordinates), "application/json")),
            ("files", ("result.json", json.dumps(result), "application/json")),
        ],
    )
    assert created.status_code == 201
    detail = client.get(f"/api/v1/surveys/{created.json()['id']}").json()
    frame = detail["result"]["frames"][0]
    assert (frame["lat"], frame["lon"]) == (55, 37)


def test_gpx_over_limit_leaves_no_files_or_survey(client, monkeypatch, tmp_path):
    monkeypatch.setattr(surveys.settings, "upload_dir", tmp_path)
    monkeypatch.setattr(surveys, "MAX_SIDECAR_BYTES", 8)
    response = client.post(
        "/api/v1/surveys",
        files=[
            ("files", ("photo.jpg", jpeg_image(), "image/jpeg")),
            ("files", ("route.gpx", b"<gpx></gpx>", "application/gpx+xml")),
        ],
    )
    assert response.status_code == 413
    assert list(tmp_path.iterdir()) == []
    assert client.get("/api/v1/surveys").json() == []
