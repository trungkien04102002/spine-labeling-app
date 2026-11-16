"""Full 11-label grading endpoints (upstream SpineNet + fine-tuned CBAM).

Unlike `/infer` (segmentation + CBAM canal/foraminal only), this runs the same
CBAM path plus the vendored SpineNet pipeline and merges the results (see
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
from app.inference import reference_b
from app.inference.full_grading import build_full_grading, grading_to_csv
from app.inference.volume_io import is_picture, to_web_mask
from app.jobs import Job, jobs
from app.models_db import Annotation, Study, grading_volume_path, mark_analyzed
from app.schemas import FullGradingResult, InferResult, SegmentationResult
from app.routers.reference_b import is_visible

router = APIRouter(tags=["grade_full"])


class JobOut(BaseModel):
    id: str
    status: str
    stage: str
    percent: int
    elapsed_seconds: float
    error: str | None
    #: Label id -> name, set once the segmentation is on disk so the viewer can
    #: show it while grading continues.
    segmentation_labels: dict[int, str] | None = None

    @classmethod
    def from_job(cls, job: Job) -> "JobOut":
        return cls(
            id=job.id,
            status=job.status,
            stage=job.stage,
            percent=job.percent,
            elapsed_seconds=round(job.elapsed_seconds, 1),
            error=job.error,
            segmentation_labels=job.partial.get("segmentation_labels"),
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
    if is_picture(study.volume_path):
        raise HTTPException(
            status_code=400,
            detail=(
                "This study is a single picture. Model A needs an MRI series "
                "(a DICOM .zip, NIfTI or MHA); only model B reads pictures."
            ),
        )
    return study


def run_and_persist_full_grading(
    db: Session,
    study_id: str,
    settings: Settings,
    progress=None,
) -> FullGradingResult:
    """Run full grading and persist its outputs.

    Shared by the synchronous endpoint and the background job; keep it as the
    single implementation. Writes the result JSON, the labelled slice PNG, the
    viewer mask and a version-0 AI annotation.
    """
    study = _require_gradable_study(db, study_id)
    # Always grade the sagittal series, whichever one is being viewed.
    volume_path = grading_volume_path(db, study)
    study_dir = Path(settings.data_dir) / study_id
    study_dir.mkdir(parents=True, exist_ok=True)

    published: list[str] = []

    def step(stage: str, percent: int, mask_path: str | None = None, labels=None) -> None:
        # Publish the segmentation as soon as it exists so the viewer can draw
        # it while discs are still being graded.
        partial = {}
        if mask_path is not None:
            published.append(to_web_mask(mask_path, str(study_dir)))
            partial["segmentation_labels"] = labels
        if progress is not None:
            progress(stage, percent, **partial)

    result, png_bytes, mask_path, labels = build_full_grading(
        study_id, volume_path, progress=step
    )
    mark_analyzed(db, study)

    # The viewer mask was normally already written when the segmentation was
    # published; rewriting it would race the viewer downloading that copy.
    mask_fs_path = published[0] if published else to_web_mask(mask_path, str(study_dir))
    result.segmentation = SegmentationResult(
        mask_uri=f"/studies/{study_id}/mask.nii.gz", labels=labels
    )

    _result_path(settings, study_id).write_text(result.model_dump_json(indent=2))
    _slice_path(settings, study_id).write_bytes(png_bytes)

    # A version-0 AI annotation is the baseline that clinician corrections and
    # the feedback pipeline (correction_log) diff against.
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

    # Model B runs only after the main result is saved, never raises, and is
    # skipped while hidden from clinicians (it would only occupy the GPU).
    if is_visible(settings):
        reference_b.run_quietly(study_id, volume_path, study_dir)

    return result


@router.post("/studies/{study_id}/grade_full", response_model=FullGradingResult)
def grade_full(
    study_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FullGradingResult:
    """Grade synchronously and return the result.

    Can take many minutes on CPU; interactive clients should use
    `/grade_full/start`. Intended for scripts and tests.
    """
    return run_and_persist_full_grading(db, study_id, settings)


@router.post("/studies/{study_id}/grade_full/start", response_model=JobOut, status_code=202)
def start_grade_full(
    study_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JobOut:
    """Start grading in the background and return a job to poll at `/jobs/{id}`.

    The study is validated first (404/400). If grading is already running for
    this study, the existing job is returned.
    """
    _require_gradable_study(db, study_id)

    existing = jobs.running_for("grade_full", study_id)
    if existing is not None:
        # Concurrent runs would race over the same result files and annotation.
        return JobOut.from_job(existing)

    def work(progress) -> None:
        # The request's session closes after the response; use a fresh one.
        session = SessionLocal()
        try:
            run_and_persist_full_grading(session, study_id, settings, progress=progress)
        finally:
            session.close()

    return JobOut.from_job(jobs.start("grade_full", study_id, work))


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str) -> JobOut:
    """Return a background job's status and progress; 404 if unknown."""
    job = jobs.get(job_id)
    if job is None:
        # Unknown, or lost in a server restart; the client should then check
        # whether a result exists.
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
