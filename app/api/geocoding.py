from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.config import get_settings
from app.integrations.dgis import DgisClient, DgisError
from app.schemas.geocoding import GeocodingResponse

router = APIRouter(prefix="/geocoding", tags=["geocoding"])


def get_dgis_client() -> DgisClient:
    settings = get_settings()
    if settings.dgis_api_key is None or not settings.dgis_api_key.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="2GIS API key is not configured",
        )
    return DgisClient(
        api_key=settings.dgis_api_key.get_secret_value(),
        base_url=settings.dgis_base_url,
        locale=settings.dgis_locale,
        timeout_seconds=settings.dgis_timeout_seconds,
    )


DgisDependency = Annotated[DgisClient, Depends(get_dgis_client)]


def raise_provider_error(error: DgisError) -> None:
    if error.provider_code == 404:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error.message)
    if error.provider_code in {401, 403}:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="2GIS rejected the configured API key",
        )
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=error.message)


@router.get("/search", response_model=GeocodingResponse)
async def search_address(
    client: DgisDependency,
    query: Annotated[str, Query(alias="q", min_length=1, max_length=500)],
    page_size: Annotated[int, Query(ge=1, le=50)] = 10,
    region_id: Annotated[int | None, Query(gt=0)] = None,
) -> dict:
    try:
        return await client.search(query, page_size=page_size, region_id=region_id)
    except DgisError as error:
        raise_provider_error(error)


@router.get("/reverse", response_model=GeocodingResponse)
async def reverse_geocode(
    client: DgisDependency,
    latitude: Annotated[float, Query(alias="lat", ge=-90, le=90)],
    longitude: Annotated[float, Query(alias="lon", ge=-180, le=180)],
    radius: Annotated[int, Query(ge=0, le=2000)] = 0,
    object_type: Annotated[str | None, Query(alias="type", max_length=128)] = None,
    page_size: Annotated[int, Query(ge=1, le=50)] = 10,
) -> dict:
    try:
        return await client.reverse(
            latitude=latitude,
            longitude=longitude,
            radius=radius,
            object_type=object_type,
            page_size=page_size,
        )
    except DgisError as error:
        raise_provider_error(error)
