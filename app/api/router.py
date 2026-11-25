from fastapi import APIRouter

from app.api import (
    entities,
    entity_types,
    findings,
    geocoding,
    inspection_feed,
    jobs,
    media,
    workspaces,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(workspaces.router)
api_router.include_router(entity_types.router)
api_router.include_router(entities.router)
api_router.include_router(media.router)
api_router.include_router(jobs.router)
api_router.include_router(findings.router)
api_router.include_router(geocoding.router)
api_router.include_router(inspection_feed.router)
