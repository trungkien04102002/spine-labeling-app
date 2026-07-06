from pydantic import BaseModel


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
