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


class StudyCreate(BaseModel):
    id: str
    patient_name: str
    modality: str = "MRI"


class StudyUpdate(BaseModel):
    patient_name: str | None = None
    modality: str | None = None


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
    # Uploaded as a single 2D picture: viewable and gradable by model B only.
    is_picture: bool = False
    # The clinician's written conclusion, and when it was last saved.
    doctor_conclusion: str | None = None
    doctor_conclusion_at: datetime.datetime | None = None


class SeriesOut(BaseModel):
    """One acquisition inside a study, as listed in the viewer's series picker."""

    id: int
    series_uid: str
    description: str | None = None
    orientation: str
    num_slices: int | None = None
    is_active: bool
    # True for the series inference last ran on. Models read one sagittal
    # series; other planes are viewable only.
    analyzed_by_ai: bool = False


class ActiveSeriesUpdate(BaseModel):
    series_id: int


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


class FullGradingResult(BaseModel):
    """The 11-label per-level grading table.

    ``canal_stenosis``, ``left_foraminal`` and ``right_foraminal`` come from the
    fine-tuned CBAM model (`app/inference/grading.py`); the other 8 conditions
    come from the vendored SpineNet pipeline (`app/inference/spinenet_grading.py`).
    See `app/inference/full_grading.py::merge_gradings`.
    """

    study_id: str
    grading: list[GradingItem]
    slice_image_uri: str
    model_version: str
    # Segmentation from the same run, persisted so the viewer can overlay it and
    # the clinician can edit it via /annotations.
    segmentation: SegmentationResult | None = None
