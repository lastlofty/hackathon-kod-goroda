from typing import Any

from pydantic import BaseModel


class GeocodingResponse(BaseModel):
    provider: str
    total: int
    items: list[dict[str, Any]]
