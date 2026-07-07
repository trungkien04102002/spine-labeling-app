"""Inference endpoint: run the models on a study and persist a v0 annotation."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.inference.base import InferenceBackend, get_backend
from app.inference.volume_io import to_web_mask
from app.models_db import Annotation, Study
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
