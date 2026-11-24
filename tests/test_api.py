from fastapi.testclient import TestClient


def create_workspace(client: TestClient, slug: str = "demo-case") -> dict:
    response = client.post(
        "/api/v1/workspaces",
        json={
            "slug": slug,
            "name": f"Case {slug}",
            "settings": {"finding_statuses": ["new", "confirmed", "rejected"]},
        },
    )
    assert response.status_code == 201
    return response.json()


def create_entity_type(client: TestClient, workspace_id: str) -> dict:
    response = client.post(
        "/api/v1/entity-types",
        json={
            "workspace_id": workspace_id,
            "code": "target",
            "name": "Target object",
            "attribute_schema": {
                "type": "object",
                "properties": {"serial": {"type": "string"}},
                "required": ["serial"],
                "additionalProperties": True,
            },
        },
    )
    assert response.status_code == 201
    return response.json()


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_configurable_entity_crud_and_validation(client: TestClient) -> None:
    workspace = create_workspace(client)
    entity_type = create_entity_type(client, workspace["id"])

    invalid = client.post(
        "/api/v1/entities",
        json={
            "workspace_id": workspace["id"],
            "entity_type_id": entity_type["id"],
            "attributes": {},
        },
    )
    assert invalid.status_code == 422
    assert "serial" in invalid.json()["detail"]

    response = client.post(
        "/api/v1/entities",
        json={
            "workspace_id": workspace["id"],
            "entity_type_id": entity_type["id"],
            "external_id": "OBJECT-001",
            "name": "Object 1",
            "attributes": {"serial": "A-123", "case_specific": 42},
            "latitude": 55.75,
            "longitude": 37.61,
        },
    )
    assert response.status_code == 201
    entity = response.json()

    duplicate = client.post(
        "/api/v1/entities",
        json={
            "workspace_id": workspace["id"],
            "entity_type_id": entity_type["id"],
            "external_id": "OBJECT-001",
            "attributes": {"serial": "B-456"},
        },
    )
    assert duplicate.status_code == 409

    response = client.get(
        "/api/v1/entities",
        params={"workspace_id": workspace["id"], "min_lat": 55, "max_lat": 56},
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [entity["id"]]

    response = client.patch(
        f"/api/v1/entities/{entity['id']}",
        json={"attributes": {"serial": "A-124", "color": "blue"}},
    )
    assert response.status_code == 200
    assert response.json()["attributes"]["color"] == "blue"

    assert client.delete(f"/api/v1/entities/{entity['id']}").status_code == 204


def test_media_job_finding_flow_and_workspace_isolation(client: TestClient) -> None:
    workspace = create_workspace(client)
    other_workspace = create_workspace(client, "other-case")

    media_response = client.post(
        "/api/v1/media",
        json={
            "workspace_id": workspace["id"],
            "kind": "sensor_frame",
            "url": "https://example.test/frame.bin",
            "source": "camera-1",
            "attributes": {"channel": 4},
        },
    )
    assert media_response.status_code == 201
    media = media_response.json()

    wrong_workspace_job = client.post(
        "/api/v1/jobs",
        json={
            "workspace_id": other_workspace["id"],
            "media_id": media["id"],
            "pipeline": "detector-v1",
        },
    )
    assert wrong_workspace_job.status_code == 422

    job_response = client.post(
        "/api/v1/jobs",
        json={
            "workspace_id": workspace["id"],
            "media_id": media["id"],
            "pipeline": "detector-v1",
            "parameters": {"threshold": 0.65},
        },
    )
    assert job_response.status_code == 201
    job = job_response.json()

    finding_response = client.post(
        "/api/v1/findings",
        json={
            "workspace_id": workspace["id"],
            "media_id": media["id"],
            "job_id": job["id"],
            "category": "classification",
            "label": "anomaly",
            "status": "new",
            "score": 0.97,
            "geometry": {"type": "bbox", "x": 10, "y": 20, "width": 100, "height": 80},
            "attributes": {"model_version": "1.0"},
            "source": "model",
        },
    )
    assert finding_response.status_code == 201
    finding = finding_response.json()

    response = client.get(
        "/api/v1/findings",
        params={"workspace_id": workspace["id"], "job_id": job["id"], "status": "new"},
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [finding["id"]]

    response = client.patch(
        f"/api/v1/jobs/{job['id']}",
        json={"status": "succeeded", "result": {"findings": 1}},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"

    response = client.patch(
        f"/api/v1/findings/{finding['id']}", json={"reviewed": True}
    )
    assert response.status_code == 200
    assert response.json()["reviewed"] is True


def test_upload_requires_workspace_and_validates_content_type(
    client: TestClient,
) -> None:
    workspace = create_workspace(client)

    response = client.post(
        "/api/v1/media/upload",
        files={"file": ("frame.txt", b"not an image", "text/plain")},
        data={"workspace_id": workspace["id"]},
    )
    assert response.status_code == 415

    response = client.post(
        "/api/v1/media/upload",
        files={"file": ("frame.png", b"fake-png", "image/png")},
        data={
            "workspace_id": workspace["id"],
            "kind": "camera_frame",
            "latitude": "55.75",
            "longitude": "37.61",
        },
    )
    assert response.status_code == 201
    assert response.json()["workspace_id"] == workspace["id"]
    assert response.json()["kind"] == "camera_frame"
    assert response.json()["url"].startswith("/uploads/")
