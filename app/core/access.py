import base64
import binascii
from secrets import compare_digest

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings


async def protect_access(request: Request, call_next):
    settings = get_settings()
    if settings.access_password is None or (
        request.method == "GET" and request.url.path == "/health"
    ):
        return await call_next(request)

    scheme, _, encoded = request.headers.get("authorization", "").partition(" ")
    supplied = b""
    if scheme.lower() == "basic":
        try:
            supplied = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            pass
    expected = f"operator:{settings.access_password.get_secret_value()}".encode()
    if not compare_digest(supplied, expected):
        return JSONResponse(
            {"detail": "Authentication required"},
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Inspection", charset="UTF-8"'},
        )

    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if (
            (origin is not None and origin != settings.public_origin)
            or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return JSONResponse({"detail": "Cross-origin write denied"}, status_code=403)

    return await call_next(request)
