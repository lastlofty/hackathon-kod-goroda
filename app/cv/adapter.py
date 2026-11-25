"""CV engineer owns the actual model contract in this module."""
from dataclasses import dataclass
from typing import Any

from PIL import Image
from pydantic import BaseModel, Field, model_validator


class AdapterNotConfigured(RuntimeError):
    pass


class Detection(BaseModel):
    category: str = Field(min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=255)
    score: float = Field(ge=0, le=1)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)
    attributes: dict[str, Any] = Field(default_factory=dict)
    severity: float | None = Field(default=None, allow_inf_nan=False)
    recommendation: str | None = None

    @model_validator(mode="after")
    def inside_image(self):
        if self.x + self.width > 1.000000001 or self.y + self.height > 1.000000001:
            raise ValueError("Bounding box must fit the original image")
        return self

    def geometry(self) -> dict:
        return {"type": "bbox", "coordinate_space": "normalized", "x": self.x,
                "y": self.y, "width": self.width, "height": self.height}


@dataclass
class PreparedInput:
    inputs: list[dict[str, Any]]
    output_names: list[str]
    context: Any = None  # e.g. resize/letterbox metadata


def preprocess(image: Image.Image, parameters: dict) -> PreparedInput:
    # CV TODO: RGB/resize/letterbox, normalization, dtype/layout, tensor names.
    # Each input: {"name": ..., "shape": [...], "datatype": ..., "data": flat_list}
    raise AdapterNotConfigured("CV preprocessing contract is not implemented")


def postprocess(outputs: dict[str, dict], image: Image.Image,
                prepared: PreparedInput, parameters: dict) -> list[Detection]:
    # CV TODO: decode actual outputs, confidence filter/NMS if required,
    # reverse letterbox, map classes and normalize to the ORIGINAL image.
    raise AdapterNotConfigured("CV postprocessing contract is not implemented")


def mock_detections(image: Image.Image, parameters: dict) -> list[Detection]:
    # Synthetic data only; deliberately not labelled as an actual MGTS object.
    return [Detection(category="mock_detection", label="DEMO / MOCK", score=0.9,
                      x=0.2, y=0.15, width=0.3, height=0.6,
                      attributes={"synthetic": True})]
