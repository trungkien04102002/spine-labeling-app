"""Comparison model B: read its saved result, or run it on demand.

Whether the viewer shows model B is an admin switch, off by default. Model B
runs automatically after each grading while visible (see
`full_grading.run_and_persist_full_grading`); the POST endpoint fills in
studies that have no result yet. See `app/inference/reference_b.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.inference import reference_b
from app.models_db import Study, grading_volume_path
from app.routers.admin import require_admin

router = APIRouter(tags=["reference_b"])


def _study_dir(settings: Settings, study_id: str) -> Path:
    return Path(settings.data_dir) / study_id


class Visibility(BaseModel):
    visible: bool
    installed: bool = False


class VisibilityIn(BaseModel):
    visible: bool


def _flag_path(settings: Settings) -> Path:
    # Stored in the data dir so it survives code updates.
    return Path(settings.data_dir) / "reference_b_visible.json"


def is_visible(settings: Settings) -> bool:
    try:
        return bool(json.loads(_flag_path(settings).read_text()).get("visible"))
    except (OSError, ValueError):
        return False


@router.get("/reference_b/visibility", response_model=Visibility)
def get_visibility(settings: Settings = Depends(get_settings)) -> Visibility:
    """Return whether model B is shown to clinicians and whether it is installed."""
    return Visibility(visible=is_visible(settings), installed=reference_b.available())


@router.put(
    "/reference_b/visibility", response_model=Visibility, dependencies=[Depends(require_admin)]
)
def set_visibility(
    payload: VisibilityIn, settings: Settings = Depends(get_settings)
) -> Visibility:
    """Show or hide model B for clinicians (admin only)."""
    path = _flag_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"visible": payload.visible}))
    return Visibility(visible=payload.visible, installed=reference_b.available())


@router.get("/studies/{study_id}/reference_b", response_model=reference_b.ReferenceResult)
def get_reference_b(
    study_id: str, settings: Settings = Depends(get_settings)
) -> reference_b.ReferenceResult:
    """Return model B's saved result for a study; 404 if it has not run."""
    result = reference_b.load_result(_study_dir(settings, study_id))
    if result is None:
        raise HTTPException(status_code=404, detail="Model B has not run on this study.")
    return result


@router.post("/studies/{study_id}/reference_b", response_model=reference_b.ReferenceResult)
def run_reference_b(
    study_id: str,
    plane: str = "sagittal",
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> reference_b.ReferenceResult:
    """Run model B now and return its result.

    `plane` ("sagittal" or "axial") matters only for an uploaded picture.
    Returns 503 if model B is not installed.
    """
    if plane not in reference_b.DATASET_BY_PLANE:
        raise HTTPException(status_code=400, detail="plane must be sagittal or axial")
    if not reference_b.available(plane):
        raise HTTPException(status_code=503, detail="Model B is not installed on this server.")
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    if not study.volume_path:
        raise HTTPException(status_code=400, detail="Study has no uploaded volume; upload first.")
    return reference_b.run(grading_volume_path(db, study), _study_dir(settings, study_id), plane=plane)


@router.get("/studies/{study_id}/reference_b/input.png")
def get_reference_b_input(
    study_id: str, settings: Settings = Depends(get_settings)
) -> FileResponse:
    path = _study_dir(settings, study_id) / reference_b.INPUT_FILE
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Model B has not run on this study.")
    return FileResponse(str(path), media_type="image/png")
