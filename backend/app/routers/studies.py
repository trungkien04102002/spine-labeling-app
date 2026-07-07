"""Study endpoints: uploading a volume and converting it for the viewer."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.inference.volume_io import read_metadata, to_web_form
from app.models_db import Patient, Study
from app.schemas import StudyDetail

router = APIRouter(tags=["studies"])


@router.get("/studies/{study_id}", response_model=StudyDetail)
def get_study_detail(
    study_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StudyDetail:
    """Return study + patient + image metadata for the viewer header."""
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    patient = db.get(Patient, study.patient_id)

    detail = StudyDetail(
        id=study.id,
        patient_id=study.patient_id,
        patient_name=patient.name if patient else "unknown",
        modality=study.modality,
        created_at=study.created_at,
        has_volume=bool(study.volume_path),
        has_mask=(Path(settings.data_dir) / study_id / "mask.nii.gz").is_file(),
    )
    # Image metadata comes from the viewer NIfTI (already reoriented).
    if study.display_path and Path(study.display_path).is_file():
        meta = read_metadata(study.display_path)
        detail.dimensions = meta["dimensions"]  # type: ignore[assignment]
        detail.spacing_mm = meta["spacing_mm"]  # type: ignore[assignment]
        detail.num_slices = meta["num_slices"]  # type: ignore[assignment]
    return detail


@router.post("/studies/{study_id}/upload")
def upload_study(
    study_id: str,
    file: UploadFile,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """Store an uploaded volume, convert it to a viewer NIfTI, record paths.

    The study row must already exist (created via demo import / patient flow).
    """
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")

    study_dir = Path(settings.data_dir) / study_id
    study_dir.mkdir(parents=True, exist_ok=True)

    filename = Path(file.filename or "volume").name
    dest = study_dir / filename
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    display_path = to_web_form(str(dest), out_dir=str(study_dir))

    study.volume_path = str(dest.resolve())
    study.display_path = display_path
    db.commit()

    return {
        "study_id": study_id,
        "volume_path": study.volume_path,
        "display_path": study.display_path,
    }


# The `.nii.gz` suffix is load-bearing: the Cornerstone NIfTI loader decides
# whether to gunzip by whether the URL path ends in ".gz".
@router.get("/studies/{study_id}/display.nii.gz")
def get_display_volume(
    study_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Serve the study's viewer NIfTI so the browser (Cornerstone3D) can load it."""
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    if not study.display_path or not Path(study.display_path).is_file():
        raise HTTPException(status_code=404, detail="No display volume for study.")
    return FileResponse(
        study.display_path,
        media_type="application/gzip",
        filename=f"{study_id}.nii.gz",
    )


# Same `.nii.gz` suffix rule as the display volume (Cornerstone gunzips on it).
@router.get("/studies/{study_id}/mask.nii.gz")
def get_mask_volume(
    study_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Serve the study's segmentation labelmap (written by ``/infer``)."""
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    mask_path = Path(settings.data_dir) / study_id / "mask.nii.gz"
    if not mask_path.is_file():
        raise HTTPException(
            status_code=404, detail="No segmentation mask; run inference first."
        )
    return FileResponse(
        str(mask_path),
        media_type="application/gzip",
        filename=f"{study_id}_mask.nii.gz",
    )
