from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Fraction = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class Rectangle(BaseModel):
    type: Literal["bbox"]
    label: Label
    x: Fraction
    y: Fraction
    w: Fraction
    h: Fraction

    @model_validator(mode="after")
    def check_bounds(self):
        if min(self.w, self.h) <= 0 or max(self.x + self.w, self.y + self.h) > 1 + 1e-10:
            raise ValueError("Rectangle outside image")
        return self


class Path(BaseModel):
    type: Literal["polygon", "polyline"]
    label: Label
    points: list[tuple[Fraction, Fraction]] = Field(min_length=2, max_length=16384)

    @model_validator(mode="after")
    def check_vertices(self):
        distinct = list(dict.fromkeys(self.points))
        if len(distinct) < (3 if self.type == "polygon" else 2):
            raise ValueError("Too few distinct vertices")
        if self.type == "polygon":
            (x, y), (a, b) = distinct[:2]
            if not any(abs((a-x)*(v-y)-(b-y)*(u-x)) > 1e-12 for u, v in distinct[2:]):
                raise ValueError("Polygon vertices are collinear")
        return self


Shape = Annotated[Rectangle | Path, Field(discriminator="type")]


class AnnotationUpdate(BaseModel):
    base_version: int = Field(ge=0)
    author: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    changes: dict[Label, Shape | None] = Field(min_length=1, max_length=4096)


class RevisionInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    author: str
    created_at: datetime
    changed_ids: list[str]


class RevisionRead(RevisionInfo):
    overrides: dict[str, Shape | None]
