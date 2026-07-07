"""Inference endpoint: run the models on a study and persist a v0 annotation."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.inference.base import InferenceBackend, get_backend
from app.inference.volume_io import to_web_mask
from app.models_db import Annotation, CorrectionLog, Study
from app.schemas import InferResult

router = APIRouter(tags=["infer"])


@router.post("/studies/{study_id}/infer", response_model=InferResult)
def infer_study(
    study_id: str,
    db: Session = Depends(get_db),
    backend: InferenceBackend = Depends(get_backend),
    settings: Settings = Depends(get_settings),
) -> InferResult:
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    if not study.volume_path:
        raise HTTPException(
            status_code=400, detail="Study has no uploaded volume; upload first."
        )

    result = backend.infer(study_id, study.volume_path)

    # Reorient the raw labelmap into the study dir so it aligns with the viewer
    # volume, then expose it via the API path (the on-disk path stays internal).
    study_dir = Path(settings.data_dir) / study_id
    mask_fs_path = to_web_mask(result.segmentation.mask_uri, str(study_dir))
    result.segmentation.mask_uri = f"/studies/{study_id}/mask.nii.gz"

    db.add(
        Annotation(
            study_id=study_id,
            version=0,
            kind="ai",
            payload_json=result.model_dump(),
            mask_path=mask_fs_path,
        )
    )
    db.commit()

    return result


@router.get("/studies/{study_id}/annotation", response_model=InferResult)
def get_latest_annotation(
    study_id: str,
    db: Session = Depends(get_db),
) -> InferResult:
    """Return the most recent annotation's results (AI or corrected)."""
    ann = (
        db.query(Annotation)
        .filter_by(study_id=study_id)
        .order_by(desc(Annotation.version), desc(Annotation.id))
        .first()
    )
    if ann is None:
        raise HTTPException(
            status_code=404, detail="No annotation yet; run inference first."
        )
    return InferResult(**ann.payload_json)


def _grading_severity_map(payload: dict) -> dict[str, str]:
    """Map "{level}/{condition}" -> severity for diffing two grade sets."""
    return {
        f"{g['level']}/{g['condition']}": g["severity"]
        for g in payload.get("grading", [])
    }


@router.put("/studies/{study_id}/annotations", response_model=InferResult)
def save_annotation(
    study_id: str,
    edited: InferResult,
    db: Session = Depends(get_db),
) -> InferResult:
    """Persist a doctor's corrected annotation as a new version.

    Bumps the version, marks it ``kind='corrected'``, carries the prior mask
    path forward (mask editing is separate), and logs each severity change to
    ``correction_log`` (the raw material for the future feedback loop).
    """
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")

    prior = (
        db.query(Annotation)
        .filter_by(study_id=study_id)
        .order_by(desc(Annotation.version), desc(Annotation.id))
        .first()
    )
    next_version = (prior.version + 1) if prior else 0

    payload = edited.model_dump()
    # Log severity diffs against the prior version.
    if prior:
        old_map = _grading_severity_map(prior.payload_json)
        for field, new_sev in _grading_severity_map(payload).items():
            old_sev = old_map.get(field)
            if old_sev is not None and old_sev != new_sev:
                db.add(
                    CorrectionLog(
                        study_id=study_id, field=field, old=old_sev, new=new_sev
                    )
                )

    db.add(
        Annotation(
            study_id=study_id,
            version=next_version,
            kind="corrected",
            payload_json=payload,
            mask_path=prior.mask_path if prior else None,
        )
    )
    db.commit()
    return edited
