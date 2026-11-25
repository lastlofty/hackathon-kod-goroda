import json
import os
import socket
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SCRIPT = textwrap.dedent(
    """
    import sys

    if __BLOCK__:
        class BlockHttpx2:
            def find_spec(self, name, path=None, target=None):
                if name == "httpx2" or name.startswith("httpx2."):
                    raise ModuleNotFoundError("No module named 'httpx2'")
                return None

        sys.meta_path.insert(0, BlockHttpx2())

    import uvicorn

    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=__PORT__, log_level="error")
    """
)

SHADOW_MODULES = {
    "broken": "raise RuntimeError('broken httpx2 distribution')\n",
    "incompatible": "",
    "failing": textwrap.dedent(
        """
        class TimeoutException(Exception):
            pass


        class RequestError(Exception):
            pass


        class AsyncClient:
            def __init__(self, **kwargs):
                raise TypeError("unexpected keyword argument 'timeout'")
        """
    ),
}


def free_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return candidate.getsockname()[1]


def http_get(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def wait_until_ready(base_url: str, process: subprocess.Popen, deadline: float) -> None:
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"server exited early with code {process.returncode}")
        try:
            http_get(f"{base_url}/health")
            return
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.2)
    raise AssertionError("server did not become ready in time")


def run_scenario(mode: str, expected_geocoding: int, tmp_path: Path) -> None:
    port = free_port()
    extra_path = ""
    if mode in SHADOW_MODULES:
        (tmp_path / "httpx2.py").write_text(
            SHADOW_MODULES[mode], encoding="utf-8"
        )
        extra_path = str(tmp_path)

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [value for value in (extra_path, str(PROJECT_ROOT)) if value]
    )
    env["DATABASE_URL"] = f"sqlite:///{(tmp_path / 'isolation.db').as_posix()}"
    env["UPLOAD_DIR"] = str(tmp_path / "uploads")
    env["DGIS_API_KEY"] = "test-key"

    code = SCRIPT.replace("__BLOCK__", str(mode == "missing")).replace(
        "__PORT__", str(port)
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        wait_until_ready(base_url, process, time.monotonic() + 30)
        health_status, _ = http_get(f"{base_url}/health")
        geocoding_status, geocoding_body = http_get(
            f"{base_url}/api/v1/geocoding/search?q=%D0%9C%D0%BE%D1%81%D0%BA%D0%B2%D0%B0"
        )
    finally:
        process.terminate()
        try:
            _, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            _, stderr = process.communicate()

    assert health_status == 200, stderr
    assert geocoding_status == expected_geocoding, stderr
    assert geocoding_body.get("detail")


@pytest.mark.parametrize(
    ("mode", "expected_geocoding"),
    [("broken", 503), ("missing", 503), ("incompatible", 503), ("failing", 502)],
)
def test_app_survives_unavailable_httpx2(
    mode: str, expected_geocoding: int, tmp_path: Path
) -> None:
    run_scenario(mode, expected_geocoding, tmp_path)
