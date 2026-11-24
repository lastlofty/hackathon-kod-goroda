from dataclasses import dataclass
from typing import Any

import httpx2


class DgisError(Exception):
    """A safe integration error that does not expose credentials."""

    def __init__(self, message: str, provider_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.provider_code = provider_code


@dataclass(frozen=True)
class DgisClient:
    api_key: str
    base_url: str
    locale: str = "ru_RU"
    timeout_seconds: float = 10

    async def search(
        self,
        query: str,
        page_size: int = 10,
        region_id: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "q": query,
            "page_size": page_size,
            "fields": "items.point,items.geometry.centroid,items.address,items.adm_div",
        }
        if region_id is not None:
            params["region_id"] = region_id
        return await self._request(params)

    async def reverse(
        self,
        latitude: float,
        longitude: float,
        radius: int = 0,
        object_type: str | None = None,
        page_size: int = 10,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "lat": latitude,
            "lon": longitude,
            "radius": radius,
            "page_size": page_size,
            "fields": "items.adm_div,items.address,items.point,items.geometry.centroid",
        }
        if object_type:
            params["type"] = object_type
        return await self._request(params)

    async def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        request_params = {**params, "key": self.api_key, "locale": self.locale}
        url = f"{self.base_url.rstrip('/')}/3.0/items/geocode"

        try:
            async with httpx2.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(url, params=request_params)
                payload = response.json()
        except httpx2.TimeoutException as exc:
            raise DgisError("2GIS request timed out") from exc
        except (httpx2.RequestError, ValueError) as exc:
            raise DgisError("2GIS service is unavailable") from exc

        meta = payload.get("meta", {})
        provider_code = meta.get("code")
        if response.status_code != 200 or provider_code != 200:
            provider_error = meta.get("error", {})
            message = provider_error.get("message") or "2GIS request failed"
            raise DgisError(
                message, provider_code=provider_code or response.status_code
            )

        result = payload.get("result", {})
        return {
            "provider": "2gis",
            "total": result.get("total", 0),
            "items": result.get("items", []),
        }
