"""Study endpoints: uploading a volume and converting it for the viewer."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.inference.volume_io import to_web_form
from app.models_db import Study

router = APIRouter(tags=["studies"])


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


@router.get("/studies/{study_id}/display")
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
