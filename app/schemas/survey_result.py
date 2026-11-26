from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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


DefectName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]


def with_defects(value):
    if not isinstance(value, dict) or "defect" not in value:
        return value
    data = dict(value)
    old = data.pop("defect", None)
    legacy = [] if not old or old in ("none", "normal", "ok") else [old]
    if (
        legacy
        and "defects" in data
        and (not isinstance(data["defects"], list) or old not in data["defects"])
    ):
        raise ValueError("Поля defect и defects противоречат друг другу")
    data.setdefault("defects", legacy)
    return data


class DefectList(BaseModel):
    defects: list[DefectName] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy(cls, value):
        return with_defects(value)

    @model_validator(mode="after")
    def unique_types(self):
        if len(set(self.defects)) != len(self.defects):
            self.defects = list(dict.fromkeys(self.defects))
        return self


class Detection(DefectList):
    inference: InferenceDetails | None = None
    det_id: Identifier
    object_id: Identifier
    category: Identifier = Field(alias="class")
    score: Score | None = None
    bbox: tuple[Score, Score, Score, Score] | None = None
    defect_score: Score | None = None

    @model_validator(mode="after")
    def nonempty_box(self):
        if self.bbox and min(self.bbox[2:]) <= 0:
            raise ValueError("Ширина и высота рамки должны быть положительными")
        return self


class Frame(Located):
    frame_id: Identifier
    analysis_note: str | None = Field(default=None, max_length=512)
    media_id: UUID | None = None
    captured_at: datetime | None = None
    detections: list[Detection]


PRIORITY_LEVELS = {1: "Критический", 2: "Высокий", 3: "Средний", 4: "Нет"}


class SurveyObject(Located, DefectList):
    description: str | None = Field(None, max_length=2048)
    verdict: Literal["ok", "defect", "unknown"] | None = None
    object_id: Identifier
    category: Identifier = Field(alias="class")
    defect_score: Score | None = None
    status: Identifier
    # Приоритет ремонта: 1 — критический (крепление), 2 — высокий (МП),
    # 3 — средний (коррозия), 4 — дефекта нет. Порядок внутри статуса.
    priority_level: int | None = Field(default=None, ge=1, le=4)
    defects: list[DefectName] = Field(
        default_factory=list, max_length=16
    )
    severity: Score | None = None
    recommendation: str | None = Field(default=None, max_length=1024)
    observations: list[Identifier] = Field(min_length=1)
    best_det_id: Identifier


class SurveyResult(BaseModel):
    source: Literal["model", "dataset"] = "model"
    frames: list[Frame]
    objects: list[SurveyObject]

    @model_validator(mode="after")
    def check_links(self):
        if len({f.frame_id for f in self.frames}) != len(self.frames):
            raise ValueError("Повтор frame_id")
        if len({o.object_id for o in self.objects}) != len(self.objects):
            raise ValueError("Повтор object_id")
        dets = [d for f in self.frames for d in f.detections]
        if self.source != "dataset" and any(d.bbox is None for d in dets):
            raise ValueError("Для детекции модели нужна рамка bbox")
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


class DefectDecision(DefectList):
    model_config = ConfigDict(extra="forbid")
    object_id: Identifier
    decision: Literal["confirmed", "rejected"]

    @model_validator(mode="after")
    def check_type(self):
        if self.decision == "confirmed" and not self.defects:
            raise ValueError("Укажите тип подтверждённого дефекта")
        if self.decision == "rejected" and self.defects:
            raise ValueError("Отклонение не содержит типа дефекта")
        return self


class ObjectLocation(Located):
    object_id: Identifier
    lat: float = Field(ge=-90, le=90, strict=True)
    lon: float = Field(ge=-180, le=180, strict=True)


class SurveyProgress(BaseModel):
    status: Literal["running", "failed"]
    percent: int = Field(ge=0, le=100)
    error: str | None = Field(default=None, max_length=2048)
