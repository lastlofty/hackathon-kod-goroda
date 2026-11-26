"""Run a trusted model adapter against queued inspections on the survey API."""

import argparse
import logging
import mimetypes
import os
import re
import time
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

import httpx2 as httpx

logger = logging.getLogger(__name__)
UPLOAD_PATH = re.compile(r"/uploads/[0-9a-f]{32}\.(?:jpg|jpeg|png|webp|mp4|mov|webm|bin)")


def run_next(client, infer):
    queue = client.get("/api/v1/surveys")
    queue.raise_for_status()
    for job in reversed(queue.json()):
        if job["status"] != "queued" or job.get("inference_mode"):
            continue
        base = "/api/v1/surveys/" + job["id"]
        claimed = client.post(base + "/claim")
        if claimed.status_code == 409:
            continue
        claimed.raise_for_status()
        process(client, base, infer)
        return True
    return False


def process(client, base, infer):
    percent = 0

    def progress(value):
        nonlocal percent
        client.post(
            base + "/progress", json={"status": "running", "percent": value}
        ).raise_for_status()
        percent = value

    try:
        detail = client.get(base)
        detail.raise_for_status()
        survey = detail.json()

        def publish_frame(path):
            path = Path(path)
            with path.open("rb") as image:
                response = client.post(
                    "/api/v1/media/upload",
                    data={"workspace_id": survey["workspace_id"]},
                    files={
                        "file": (path.name, image, mimetypes.guess_type(path.name)[0])
                    },
                )
            response.raise_for_status()
            return response.json()["id"]

        with TemporaryDirectory(prefix="mgts-survey-") as temp:
            inputs = []
            for item in survey["inputs"]:
                url = item["url"]
                if not UPLOAD_PATH.fullmatch(url):
                    raise ValueError("Survey input must reference a local upload")
                path = Path(temp) / (UUID(item["id"]).hex + Path(url).suffix)
                with (
                    client.stream("GET", url) as response,
                    path.open("wb") as out,
                ):
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        out.write(chunk)
                inputs.append({**item, "path": path})
            result = infer(inputs, progress, publish_frame)
            client.post(base + "/result", json=result).raise_for_status()
    except Exception as exc:
        logger.exception("Survey processing failed for %s", base)
        response = client.post(
            base + "/progress",
            json={
                "status": "failed",
                "percent": percent,
                "error": str(exc)[:2048],
            },
        )
        if response.status_code != 409:
            response.raise_for_status()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", required=True, help="Python module:function")
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    module, function = args.adapter.split(":")
    infer = getattr(import_module(module), function)
    password = os.getenv("ACCESS_PASSWORD")
    auth = ("operator", password) if password else None
    with httpx.Client(base_url=args.api, timeout=300, auth=auth, follow_redirects=False) as client:
        while True:
            processed = run_next(client, infer)
            if args.once:
                return
            if not processed:
                time.sleep(2)


if __name__ == "__main__":
    main()
