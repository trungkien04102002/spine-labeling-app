"""Inference endpoint: run the models on a study and persist a v0 annotation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.inference.base import InferenceBackend, get_backend
from app.models_db import Annotation, Study
from app.schemas import InferResult

router = APIRouter(tags=["infer"])


@router.post("/studies/{study_id}/infer", response_model=InferResult)
def infer_study(
    study_id: str,
    db: Session = Depends(get_db),
    backend: InferenceBackend = Depends(get_backend),
) -> InferResult:
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    if not study.volume_path:
        raise HTTPException(
            status_code=400, detail="Study has no uploaded volume; upload first."
        )

    result = backend.infer(study_id, study.volume_path)

    db.add(
        Annotation(
            study_id=study_id,
            version=0,
            kind="ai",
            payload_json=result.model_dump(),
            mask_path=result.segmentation.mask_uri,
        )
    )
    db.commit()

    return result
