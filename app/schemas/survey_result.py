from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=512)]
Score = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class Located(BaseModel):
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)

    @model_validator(mode="after")
    def coordinate_pair(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat и lon задаются вместе")
        return self


class InferenceDetails(BaseModel):
    model_name: str | None = None
    model_version: str | None = None
    label: str | None = None
    severity: float | None = Field(default=None, allow_inf_nan=False)
    recommendation: str | None = None


class Detection(BaseModel):
    inference: InferenceDetails | None = None
    det_id: Identifier
    object_id: Identifier
    category: Identifier = Field(alias="class")
    score: Score | None = None
    bbox: tuple[Score, Score, Score, Score]
    defect: str | None = None
    defect_score: Score | None = None

    @model_validator(mode="after")
    def nonempty_box(self):
        if min(self.bbox[2:]) <= 0:
            raise ValueError("Ширина и высота рамки должны быть положительными")
        return self


class Frame(Located):
    frame_id: Identifier
    media_id: UUID | None = None
    captured_at: datetime | None = None
    detections: list[Detection]


class SurveyObject(Located):
    verdict: Literal["ok", "defect", "unknown"] | None = None
    recommendation: str | None = None
    object_id: Identifier
    category: Identifier = Field(alias="class")
    defect: str | None = None
    defect_score: Score | None = None
    status: Identifier
    observations: list[Identifier] = Field(min_length=1)
    best_det_id: Identifier


class SurveyResult(BaseModel):
    frames: list[Frame]
    objects: list[SurveyObject]

    @model_validator(mode="after")
    def check_links(self):
        if len({f.frame_id for f in self.frames}) != len(self.frames):
            raise ValueError("Повтор frame_id")
        if len({o.object_id for o in self.objects}) != len(self.objects):
            raise ValueError("Повтор object_id")
        dets = [d for f in self.frames for d in f.detections]
        owners = {d.det_id: d.object_id for d in dets}
        if len(owners) != len(dets):
            raise ValueError("Повтор det_id")
        used = set()
        for obj in self.objects:
            ids = set(obj.observations)
            if (
                len(ids) != len(obj.observations)
                or obj.best_det_id not in ids
                or any(owners.get(i) != obj.object_id for i in ids)
            ):
                raise ValueError(
                    f"Некорректная связь observations/best_det_id у {obj.object_id}"
                )
            used.update(ids)
        if used != set(owners):
            raise ValueError("Обнаружение не связано с итоговым объектом")
        return self


class DefectDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_id: Identifier
    decision: Literal["confirmed", "rejected"]
    defect: str | None = Field(None, max_length=256)

    @model_validator(mode="after")
    def check_type(self):
        if self.decision == "confirmed" and not (self.defect or "").strip():
            raise ValueError("Укажите тип подтверждённого дефекта")
        if self.decision == "rejected" and self.defect:
            raise ValueError("Отклонение не содержит типа дефекта")
        return self


class SurveyProgress(BaseModel):
    status: Literal["running", "failed"]
    percent: int = Field(ge=0, le=100)
    error: str | None = Field(default=None, max_length=2048)
