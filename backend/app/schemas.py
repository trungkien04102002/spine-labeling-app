import datetime

from pydantic import BaseModel


class StudyOut(BaseModel):
    id: str
    modality: str
    has_volume: bool
    created_at: datetime.datetime


class PatientOut(BaseModel):
    id: int
    name: str
    created_at: datetime.datetime
    studies: list[StudyOut]


class SegmentationResult(BaseModel):
    mask_uri: str
    labels: dict[int, str]


class GradingItem(BaseModel):
    level: str
    condition: str
    severity: str
    score: float
    bbox: list[float] | None = None
    heatmap_uri: str | None = None


class InferResult(BaseModel):
    study_id: str
    segmentation: SegmentationResult
    grading: list[GradingItem]
    model_version: str
