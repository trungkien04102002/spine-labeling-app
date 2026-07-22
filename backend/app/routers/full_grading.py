"""Full 11-label grading endpoints (upstream SpineNet + fine-tuned CBAM).

Separate from `/infer` (segmentation + CBAM canal/foraminal only) so the
existing TotalSpineSeg/CBAM path stays untouched; this endpoint runs that same
CBAM path plus the vendored upstream SpineNet pipeline and merges them (see
`app/inference/full_grading.py`).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.inference.full_grading import build_full_grading, grading_to_csv
from app.models_db import Study
from app.schemas import FullGradingResult

router = APIRouter(tags=["grade_full"])


def _result_path(settings: Settings, study_id: str) -> Path:
    return Path(settings.data_dir) / study_id / "grade_full.json"


def _slice_path(settings: Settings, study_id: str) -> Path:
    return Path(settings.data_dir) / study_id / "spinenet_slice.png"


def _load_cached_result(settings: Settings, study_id: str) -> FullGradingResult:
    path = _result_path(settings, study_id)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="No full grading yet; POST /studies/{id}/grade_full first.",
        )
    return FullGradingResult.model_validate_json(path.read_text())


@router.post("/studies/{study_id}/grade_full", response_model=FullGradingResult)
def grade_full(
    study_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FullGradingResult:
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    if not study.volume_path:
        raise HTTPException(
            status_code=400, detail="Study has no uploaded volume; upload first."
        )

    result, png_bytes = build_full_grading(study_id, study.volume_path)

    study_dir = Path(settings.data_dir) / study_id
    study_dir.mkdir(parents=True, exist_ok=True)
    _result_path(settings, study_id).write_text(result.model_dump_json(indent=2))
    _slice_path(settings, study_id).write_bytes(png_bytes)

    return result


@router.get("/studies/{study_id}/grade_full", response_model=FullGradingResult)
def get_grade_full(
    study_id: str,
    settings: Settings = Depends(get_settings),
) -> FullGradingResult:
    """Return the most recently computed full grading (no recomputation)."""
    return _load_cached_result(settings, study_id)


@router.get("/studies/{study_id}/grade_full.csv")
def get_grade_full_csv(
    study_id: str,
    settings: Settings = Depends(get_settings),
) -> Response:
    result = _load_cached_result(settings, study_id)
    return Response(
        content=grading_to_csv(result.grading),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{study_id}_grade_full.csv"'
        },
    )


@router.get("/studies/{study_id}/grade_full.json")
def get_grade_full_json(
    study_id: str,
    settings: Settings = Depends(get_settings),
) -> Response:
    path = _result_path(settings, study_id)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="No full grading yet; POST /studies/{id}/grade_full first.",
        )
    return Response(
        content=path.read_text(),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{study_id}_grade_full.json"'
        },
    )


@router.get("/studies/{study_id}/grade_full/slice.png")
def get_grade_full_slice(
    study_id: str,
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    path = _slice_path(settings, study_id)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="No labelled slice yet; POST /studies/{id}/grade_full first.",
        )
    return FileResponse(str(path), media_type="image/png")
