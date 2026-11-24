from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import get_settings

settings = get_settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=settings.app_name, version="0.1.0")
app.include_router(api_router)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}
