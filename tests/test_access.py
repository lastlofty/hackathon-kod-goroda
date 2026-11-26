from base64 import b64encode

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings, get_settings


def test_wide_bind_requires_password():
    with pytest.raises(ValidationError, match="requires ACCESS_PASSWORD"):
        Settings(backend_bind="0.0.0.0", access_password=None)


def test_protected_pilot_requires_https_origin():
    with pytest.raises(ValidationError, match="must be an HTTPS origin"):
        Settings(access_password=SecretStr("x" * 24), public_origin="http://pilot.test")


def test_access_gate_covers_api_files_and_docs(client, monkeypatch):
    settings = get_settings()
    password = "test-" + "x" * 24
    origin = "https://pilot.test"
    monkeypatch.setattr(settings, "access_password", SecretStr(password))
    monkeypatch.setattr(settings, "public_origin", origin)
    token = b64encode(f"operator:{password}".encode()).decode()
    auth = {"Authorization": f"Basic {token}"}

    for path in ("/api/v1/workspaces", "/uploads/photo.jpg", "/docs", "/openapi.json"):
        response = client.get(path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"].startswith("Basic ")
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/workspaces", headers=auth).status_code == 200

    workspace = {"slug": "pilot", "name": "Pilot"}
    for extra in ({"Origin": "https://other.test"}, {"Sec-Fetch-Site": "cross-site"}):
        response = client.post(
            "/api/v1/workspaces", json=workspace, headers={**auth, **extra}
        )
        assert response.status_code == 403
    response = client.post(
        "/api/v1/workspaces", json=workspace, headers={**auth, "Origin": origin}
    )
    assert response.status_code == 201
