from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event, Thread

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.access import protect_access
from app.core.config import get_settings
from app.services.survey_detection import run_queue

settings = get_settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app):
    if settings.inference_mode == "disabled":
        yield
        return
    stop = Event()
    worker = Thread(
        target=run_queue, args=(settings, stop), name="survey-detection", daemon=True
    )
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=settings.triton_timeout_seconds + 5)


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)
app.middleware("http")(protect_access)
app.include_router(api_router)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


frontend = Path(__file__).resolve().parents[1] / "frontend"
if (frontend / "index.html").is_file():
    # The standalone page points to the local API. The bundled UI uses its own origin.
    index_html = (frontend / "index.html").read_text(encoding="utf-8").replace(
        'name="mgts-backend-api" content="http://localhost:8080"',
        'name="mgts-backend-api" content="/"',
    )

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/index.html", response_class=HTMLResponse, include_in_schema=False)
    def index() -> str:
        return index_html

    app.mount("/", StaticFiles(directory=frontend), name="frontend")
