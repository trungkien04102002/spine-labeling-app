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


class StudyDetail(BaseModel):
    """Study + patient + image metadata shown in the viewer header."""

    id: str
    patient_id: int
    patient_name: str
    modality: str
    created_at: datetime.datetime
    has_volume: bool
    has_mask: bool
    dimensions: list[int] | None = None
    spacing_mm: list[float] | None = None
    num_slices: int | None = None
    # Acquisition tags from the source DICOM (empty for MHA/NIfTI sources).
    dicom_tags: dict[str, str] = {}


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
