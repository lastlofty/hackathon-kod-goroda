from fastapi import APIRouter

from app.api import assets, inspections, media


api_router = APIRouter(prefix="/api/v1")
api_router.include_router(assets.router)
api_router.include_router(media.router)
api_router.include_router(inspections.router)
