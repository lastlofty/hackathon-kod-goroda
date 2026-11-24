from fastapi.testclient import TestClient


def create_asset(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/assets",
        json={
            "external_id": "WELL-001",
            "asset_type": "cable_well",
            "name": "Колодец 1",
            "latitude": 55.75,
            "longitude": 37.61,
            "address": "Москва",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_asset_crud_and_map_filter(client: TestClient) -> None:
    asset = create_asset(client)

    duplicate = client.post(
        "/api/v1/assets",
        json={
            "external_id": "WELL-001",
            "asset_type": "cable_well",
            "latitude": 55.75,
            "longitude": 37.61,
        },
    )
    assert duplicate.status_code == 409

    response = client.get("/api/v1/assets", params={"min_lat": 55, "max_lat": 56})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [asset["id"]]

    response = client.patch(f"/api/v1/assets/{asset['id']}", json={"name": "Колодец 1А"})
    assert response.status_code == 200
    assert response.json()["name"] == "Колодец 1А"

    response = client.delete(f"/api/v1/assets/{asset['id']}")
    assert response.status_code == 204
    assert client.get(f"/api/v1/assets/{asset['id']}").status_code == 404


def test_media_and_inspection_crud(client: TestClient) -> None:
    asset = create_asset(client)
    media_response = client.post(
        "/api/v1/media",
        json={
            "media_type": "image",
            "url": "https://example.test/frame.jpg",
            "latitude": 55.75,
            "longitude": 37.61,
            "source": "demo",
        },
    )
    assert media_response.status_code == 201
    media = media_response.json()

    inspection_response = client.post(
        "/api/v1/inspections",
        json={
            "asset_id": asset["id"],
            "media_id": media["id"],
            "condition": "repair",
            "defect_type": "open_hatch",
            "confidence": 0.97,
            "severity": 90,
            "recommendation": "Проверить и закрыть люк",
            "bbox": {"x": 10, "y": 20, "width": 100, "height": 80},
            "model_name": "detector",
            "model_version": "0.1",
        },
    )
    assert inspection_response.status_code == 201
    inspection = inspection_response.json()

    response = client.get("/api/v1/inspections", params={"asset_id": asset["id"]})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [inspection["id"]]

    response = client.patch(
        f"/api/v1/inspections/{inspection['id']}", json={"reviewed": True}
    )
    assert response.status_code == 200
    assert response.json()["reviewed"] is True

    assert client.delete(f"/api/v1/inspections/{inspection['id']}").status_code == 204
    assert client.delete(f"/api/v1/media/{media['id']}").status_code == 204


def test_image_upload_validation(client: TestClient) -> None:
    response = client.post(
        "/api/v1/media/upload",
        files={"file": ("frame.txt", b"not an image", "text/plain")},
    )
    assert response.status_code == 415

    response = client.post(
        "/api/v1/media/upload",
        files={"file": ("frame.png", b"fake-png", "image/png")},
        data={"latitude": "55.75", "longitude": "37.61"},
    )
    assert response.status_code == 201
    assert response.json()["url"].startswith("/uploads/")
