from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image


def jpeg() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 24), "grey").save(buffer, "JPEG")
    return buffer.getvalue()


def queued_survey(client: TestClient) -> str:
    response = client.post(
        "/api/v1/surveys",
        files=[("files", ("shot.jpg", jpeg(), "image/jpeg"))],
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def result(**object_fields) -> dict:
    return {
        "frames": [
            {
                "frame_id": "shot.jpg",
                "detections": [
                    {
                        "det_id": "shot.jpg#0",
                        "object_id": "OBJ-0001",
                        "class": "RSH",
                        "score": 0.4,
                        "bbox": [0.5, 0.5, 0.2, 0.3],
                        "defect": "Механическое повреждение",
                        "defect_score": 0.9,
                    }
                ],
            }
        ],
        "objects": [
            {
                "object_id": "OBJ-0001",
                "class": "RSH",
                "status": "urgent",
                "observations": ["shot.jpg#0"],
                "best_det_id": "shot.jpg#0",
                **object_fields,
            }
        ],
    }


def test_priority_and_recommendation_are_kept(client: TestClient) -> None:
    survey_id = queued_survey(client)
    payload = result(
        verdict="defect",
        defect="Механическое повреждение",
        defect_score=0.9,
        priority_level=2,
        defects=["Механическое повреждение", "Коррозия / повреждение ЛКП"],
        severity=0.68,
        recommendation="Ремонт корпуса в ближайший выезд",
    )
    response = client.post(f"/api/v1/surveys/{survey_id}/result", json=payload)
    assert response.status_code == 200, response.text

    stored = client.get(f"/api/v1/surveys/{survey_id}").json()["result"]["objects"][0]
    assert stored["priority_level"] == 2
    assert stored["defects"] == payload["objects"][0]["defects"]
    assert stored["severity"] == 0.68
    assert stored["recommendation"] == "Ремонт корпуса в ближайший выезд"


def test_priority_fields_are_optional(client: TestClient) -> None:
    survey_id = queued_survey(client)
    response = client.post(f"/api/v1/surveys/{survey_id}/result", json=result())
    assert response.status_code == 200, response.text

    stored = client.get(f"/api/v1/surveys/{survey_id}").json()["result"]["objects"][0]
    for field in ("priority_level", "defects", "severity", "recommendation"):
        assert field not in stored


def test_priority_level_is_validated(client: TestClient) -> None:
    survey_id = queued_survey(client)
    for bad in ({"priority_level": 7}, {"severity": 1.5}):
        response = client.post(f"/api/v1/surveys/{survey_id}/result", json=result(**bad))
        assert response.status_code == 422, (bad, response.text)
