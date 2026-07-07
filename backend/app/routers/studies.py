"""Study endpoints: uploading a volume and converting it for the viewer."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.export import build_export_zip
from app.inference.volume_io import read_dicom_tags, read_metadata, to_web_form
from app.models_db import Annotation, CorrectionLog, Patient, Study
from app.schemas import StudyCreate, StudyDetail, StudyUpdate

router = APIRouter(tags=["studies"])


@router.post("/studies", status_code=201)
def create_study(
    payload: StudyCreate,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Create a new (empty) study + its patient; a volume is uploaded later."""
    if db.get(Study, payload.id) is not None:
        raise HTTPException(
            status_code=409, detail=f"Study '{payload.id}' already exists."
        )
    # Group studies under one patient: reuse an existing patient of the same
    # name, otherwise create a new one.
    name = payload.patient_name.strip() or "Unknown"
    patient = db.query(Patient).filter_by(name=name).first()
    if patient is None:
        patient = Patient(name=name)
        db.add(patient)
        db.commit()
        db.refresh(patient)
    study = Study(id=payload.id, patient_id=patient.id, modality=payload.modality)
    db.add(study)
    db.commit()
    return {"id": study.id, "patient_id": patient.id}


@router.patch("/studies/{study_id}")
def update_study(
    study_id: str,
    payload: StudyUpdate,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Edit a study's modality and/or its patient's name."""
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    if payload.modality is not None:
        study.modality = payload.modality
    if payload.patient_name is not None:
        patient = db.get(Patient, study.patient_id)
        if patient is not None:
            patient.name = payload.patient_name.strip() or patient.name
    db.commit()
    return {"id": study.id, "modality": study.modality}


@router.delete("/studies/{study_id}", status_code=204)
def delete_study(
    study_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Delete a study, its annotations/logs, and its files on disk."""
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    db.query(Annotation).filter_by(study_id=study_id).delete()
    db.query(CorrectionLog).filter_by(study_id=study_id).delete()
    db.delete(study)
    db.commit()
    shutil.rmtree(Path(settings.data_dir) / study_id, ignore_errors=True)
    return Response(status_code=204)


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
    # Acquisition tags survive only in the original DICOM (not the NIfTI).
    if study.volume_path:
        detail.dicom_tags = read_dicom_tags(study.volume_path)
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
        # The mask changes when a doctor saves edits; never serve a stale copy.
        headers={"Cache-Control": "no-store"},
    )


@router.put("/studies/{study_id}/mask")
async def save_mask(
    study_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Persist a doctor-edited labelmap (raw uint8 voxels, display geometry).

    The frontend sends the edited Cornerstone labelmap as a flat little-endian
    uint8 buffer in slice order (z, y, x); we reshape it to the display volume's
    size, copy that volume's geometry, and overwrite ``mask.nii.gz``.
    """
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    if not study.display_path or not Path(study.display_path).is_file():
        raise HTTPException(status_code=400, detail="Study has no display volume.")

    raw = await request.body()
    display = sitk.ReadImage(study.display_path)
    x, y, z = display.GetSize()  # (x, y, z)
    expected = x * y * z
    arr = np.frombuffer(raw, dtype=np.uint8)
    if arr.size != expected:
        raise HTTPException(
            status_code=400,
            detail=f"Mask size {arr.size} != expected {expected} ({z}x{y}x{x}).",
        )

    mask_img = sitk.GetImageFromArray(arr.reshape((z, y, x)).astype(np.uint16))
    mask_img.CopyInformation(display)
    mask_path = Path(settings.data_dir) / study_id / "mask.nii.gz"
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(mask_img, str(mask_path))
    return {"ok": True, "shape": [z, y, x]}


@router.get("/studies/{study_id}/export")
def export_study(
    study_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Export the latest annotation as a zip (original + mask + grades + PNG)."""
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    ann = (
        db.query(Annotation)
        .filter_by(study_id=study_id)
        .order_by(desc(Annotation.version), desc(Annotation.id))
        .first()
    )
    if ann is None:
        raise HTTPException(
            status_code=404, detail="No annotation to export; run inference first."
        )

    mask_path = Path(settings.data_dir) / study_id / "mask.nii.gz"
    zip_bytes = build_export_zip(
        study.display_path, str(mask_path), ann.payload_json
    )
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{study_id}_export.zip"'
        },
    )
