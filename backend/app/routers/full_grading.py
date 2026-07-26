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
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import SessionLocal, get_db
from app.inference.full_grading import build_full_grading, grading_to_csv
from app.inference.volume_io import to_web_mask
from app.jobs import Job, jobs
from app.models_db import Annotation, Study, grading_volume_path, mark_analyzed
from app.schemas import FullGradingResult, InferResult, SegmentationResult

router = APIRouter(tags=["grade_full"])


class JobOut(BaseModel):
    id: str
    status: str
    stage: str
    percent: int
    elapsed_seconds: float
    error: str | None

    @classmethod
    def from_job(cls, job: Job) -> "JobOut":
        return cls(
            id=job.id,
            status=job.status,
            stage=job.stage,
            percent=job.percent,
            elapsed_seconds=round(job.elapsed_seconds, 1),
            error=job.error,
        )


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


def _require_gradable_study(db: Session, study_id: str) -> Study:
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail=f"Unknown study: {study_id}")
    if not study.volume_path:
        raise HTTPException(
            status_code=400, detail="Study has no uploaded volume; upload first."
        )
    return study


def run_and_persist_full_grading(
    db: Session,
    study_id: str,
    settings: Settings,
    progress=None,
) -> FullGradingResult:
    """The whole grading run, shared by the sync endpoint and the background job.

    Kept as one function on purpose: two copies of this would drift, and the
    background path is the one that actually gets used, so a bug fixed in only
    the synchronous copy would never reach a doctor.
    """
    study = _require_gradable_study(db, study_id)
    # Always grade the sagittal series, whichever one the doctor is viewing.
    result, png_bytes, mask_path, labels = build_full_grading(
        study_id, grading_volume_path(db, study), progress=progress
    )
    mark_analyzed(db, study)

    study_dir = Path(settings.data_dir) / study_id
    study_dir.mkdir(parents=True, exist_ok=True)

    # Reorient the raw labelmap into the study dir (aligned to the viewer volume)
    # and expose it via the API path, exactly like /infer does.
    mask_fs_path = to_web_mask(mask_path, str(study_dir))
    result.segmentation = SegmentationResult(
        mask_uri=f"/studies/{study_id}/mask.nii.gz", labels=labels
    )

    _result_path(settings, study_id).write_text(result.model_dump_json(indent=2))
    _slice_path(settings, study_id).write_bytes(png_bytes)

    # Persist a v0 AI annotation so the editable "Abnormality grades" panel and
    # the doctor-correction / feedback pipeline (getAnnotation -> edit ->
    # /annotations -> correction_log) work on the full 11-label grading, the
    # same way they already do for /infer's InferResult.
    infer_payload = InferResult(
        study_id=study_id,
        segmentation=result.segmentation,
        grading=result.grading,
        model_version=result.model_version,
    )
    db.add(
        Annotation(
            study_id=study_id,
            version=0,
            kind="ai",
            payload_json=infer_payload.model_dump(),
            mask_path=mask_fs_path,
        )
    )
    db.commit()

    return result


@router.post("/studies/{study_id}/grade_full", response_model=FullGradingResult)
def grade_full(
    study_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FullGradingResult:
    """Grade synchronously and return the result.

    Takes 8-15 minutes on CPU, so anything with a proxy or an impatient user in
    front of it should POST to `/grade_full/start` instead. Kept because it is
    the simplest thing to call from a script or a test.
    """
    return run_and_persist_full_grading(db, study_id, settings)


@router.post("/studies/{study_id}/grade_full/start", response_model=JobOut, status_code=202)
def start_grade_full(
    study_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JobOut:
    """Start grading in the background and return a job to poll.

    Validates the study up front so an unusable request fails immediately with
    a real status code, rather than becoming a job that fails a minute later.
    """
    _require_gradable_study(db, study_id)

    existing = jobs.running_for("grade_full", study_id)
    if existing is not None:
        # Two concurrent runs would race over the same result files and the
        # same v0 annotation. Hand back the run already in flight.
        return JobOut.from_job(existing)

    def work(progress) -> None:
        # A background thread cannot borrow the request's session -- that one
        # is closed as soon as the response goes out.
        session = SessionLocal()
        try:
            run_and_persist_full_grading(session, study_id, settings, progress=progress)
        finally:
            session.close()

    return JobOut.from_job(jobs.start("grade_full", study_id, work))


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str) -> JobOut:
    job = jobs.get(job_id)
    if job is None:
        # Unknown, or the server restarted. The client should fall back to
        # asking whether a result exists.
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_id}")
    return JobOut.from_job(job)


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
