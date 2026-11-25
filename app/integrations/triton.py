"""Small synchronous Triton V2 JSON transport; no GPU/client SDK required."""
import json
import re
from typing import Any
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class TritonError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class TritonClient:
    def __init__(self, url: str, timeout: float = 30):
        parts = urlsplit(url)
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username or parts.password or parts.query or parts.fragment
                or parts.path not in {"", "/"}):
            raise ValueError("TRITON_URL must be an HTTP(S) server origin")
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    @staticmethod
    def model_path(model: str, version: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", model) or not re.fullmatch(r"[1-9][0-9]*", version):
            raise ValueError("Invalid Triton model name or version")
        return f"/v2/models/{model}/versions/{version}"

    def request(self, path: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload, allow_nan=False).encode()
        req = Request(self.url + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                limit = 64 * 1024 * 1024
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise TritonError("Triton response exceeds 64 MiB")
                result = json.loads(body) if body else {}
                if not isinstance(result, dict):
                    raise TritonError("Invalid Triton response")
                return result
        except (URLError, OSError, ValueError) as exc:
            raise TritonError("Triton request failed") from exc

    def ready(self, model: str, version: str) -> None:
        self.request(self.model_path(model, version) + "/ready")

    def infer(self, model: str, version: str, inputs: list[dict[str, Any]],
              output_names: list[str]) -> dict[str, dict[str, Any]]:
        result = self.request(self.model_path(model, version) + "/infer", {
            "inputs": inputs,
            "outputs": [{"name": name} for name in output_names],
        })
        outputs = result.get("outputs")
        if not isinstance(outputs, list):
            raise TritonError("Missing Triton outputs")
        mapped = {}
        for item in outputs:
            if (not isinstance(item, dict) or not isinstance(item.get("name"), str)
                    or not isinstance(item.get("data"), list)
                    or not isinstance(item.get("shape"), list)
                    or not isinstance(item.get("datatype"), str)
                    or item["name"] in mapped):
                raise TritonError("Invalid Triton output tensor")
            mapped[item["name"]] = item
        if set(mapped) != set(output_names):
            raise TritonError("Unexpected Triton output names")
        return mapped
