from io import BytesIO

from PIL import Image

from app.api import surveys


def upload_photos(client, monkeypatch, tmp_path):
    monkeypatch.setattr(surveys.settings, "upload_dir", tmp_path)
    with BytesIO() as buffer:
        Image.new("RGB", (2, 2)).save(buffer, format="JPEG")
        jpeg = buffer.getvalue()
    response = client.post(
        "/api/v1/surveys",
        files=[
            ("files", (name, jpeg, "image/jpeg")) for name in ("first.jpg", "second.jpg")
        ],
    )
    assert response.status_code == 201
    url = f"/api/v1/surveys/{response.json()['id']}"
    return url, client.get(url).json()["inputs"]


def frame(item):
    return {"frame_id": item["name"], "media_id": item["id"], "detections": []}


def test_survey_rejects_swapped_media_ids(client, monkeypatch, tmp_path):
    url, (first, second) = upload_photos(client, monkeypatch, tmp_path)
    result = {
        "frames": [
            {**frame(first), "media_id": second["id"]},
            {**frame(second), "media_id": first["id"]},
        ],
        "objects": [],
    }
    response = client.post(f"{url}/result", json=result)
    assert response.status_code == 422
    assert client.get(url).json()["status"] == "queued"


def test_survey_rejects_two_frames_for_same_photo(client, monkeypatch, tmp_path):
    url, (first, second) = upload_photos(client, monkeypatch, tmp_path)
    result = {
        "frames": [frame(first), frame(second), {**frame(first), "frame_id": "copy"}],
        "objects": [],
    }
    assert client.post(f"{url}/result", json=result).status_code == 422


def test_survey_preserves_object_recommendation(client, monkeypatch, tmp_path):
    url, (first, second) = upload_photos(client, monkeypatch, tmp_path)
    observation = {
        "det_id": "d1",
        "object_id": "o1",
        "class": "manhole",
        "bbox": [0.5, 0.5, 0.2, 0.2],
    }
    result = {
        "frames": [{**frame(first), "detections": [observation]}, frame(second)],
        "objects": [{
            "object_id": "o1",
            "class": "manhole",
            "status": "normal",
            "verdict": "defect",
            "observations": ["d1"],
            "best_det_id": "d1",
            "recommendation": "Проверить крепление крышки",
        }],
    }
    assert client.post(f"{url}/result", json=result).status_code == 200
    obj = client.get(url).json()["result"]["objects"][0]
    assert obj["verdict"] == "defect"
    assert obj["recommendation"] == "Проверить крепление крышки"
