"""Re-training runs started from the operator page, and the run log.

A run rebuilds the submitted corrections, fine-tunes the heads of the
checkpoint in service, scores the result on the frozen held-out set and, only
if held-out macro-F1 improves, writes a candidate checkpoint. It never changes
the ``ACTIVE`` pointer or the serving model; activation is a manual approval
step on ``/models``.

* By default a run trains on every correction submitted so far, so later
  rounds do not forget earlier corrections. ``scope="batch"`` trains on one
  batch only, which makes a past run reproducible.
* The work is delegated to ``app.feedback.build_dataset`` and
  ``app.feedback.retrain_head``; do not reimplement that logic here.
* The replay set (``RETRAIN_REPLAY_DIR``, ~8.2 GB of original RSNA discs) is
  required unless the request explicitly sets ``without_replay``; training on
  corrections alone causes catastrophic forgetting.
* One run at a time: CPU fine-tuning takes tens of minutes and uses the whole
  machine. Every attempt is recorded in ``retrain_runs``.
"""

from __future__ import annotations

import csv
import datetime
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import SessionLocal, get_db
from app.feedback import build_dataset, freeze_holdout, model_registry, retrain_head
from app.jobs import jobs
from app.jsonsafe import finite_only
from app.models_db import CorrectionLog, RetrainRun, mark_interrupted_runs
from app.routers.full_grading import JobOut

from app.routers.admin import require_admin  # noqa: E402

router = APIRouter(tags=["retraining"])

#: Job kind in the shared registry (same one full grading uses).
JOB_KIND = "retrain"

#: Environment variable behind `Settings.retrain_replay_dir`, shown in the UI.
REPLAY_SETTING = "RETRAIN_REPLAY_DIR"

#: Serialises check-then-start so two concurrent requests cannot both start a run.
_start_lock = threading.Lock()


def _holdout_dir(settings: Settings) -> Path:
    """The frozen held-out set used for all before/after metrics."""
    return Path(settings.data_dir) / "holdout_frozen"


def _dataset_dir(settings: Settings, batch_id: str, cumulative: bool) -> Path:
    """Directory a run's training data is rebuilt into.

    Keyed by the launching batch; the ``-all`` suffix keeps a cumulative
    rebuild separate from the per-batch one.
    """
    name = f"{batch_id}-all" if cumulative else batch_id
    return Path(settings.data_dir) / "finetune" / name


def _dataset_rows(directory: Path) -> int | None:
    """Row count of a `build_dataset`-shaped directory, or None if it is not one."""
    metadata = directory / "train_metadata.csv"
    if not metadata.is_file() or not (directory / "volumes").is_dir():
        return None
    try:
        with open(metadata, newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except OSError:
        return None


def _finite_only(metrics: dict | None) -> dict | None:
    """Replace NaN/inf in a metrics dict with null before JSON serialisation.

    ``retrain_head.evaluate`` reports NaN for classes absent from the held-out
    set, and the browser's ``JSON.parse`` rejects bare ``NaN``.
    """
    if not metrics:
        return metrics
    return finite_only(metrics)


def _candidate_checkpoint_path(batch_id: str, cumulative: bool) -> Path:
    """Return an unused filename for this run's candidate checkpoint.

    Never overwrites an earlier candidate, which may still await approval.
    The name includes the scope so candidates from one batch stay distinct.
    """
    weights = model_registry.WEIGHTS_DIR
    stem = f"{batch_id}-all" if cumulative else batch_id
    candidate = weights / f"{stem}.pth"
    attempt = 2
    while candidate.exists():
        candidate = weights / f"{stem}-run{attempt}.pth"
        attempt += 1
    return candidate


class ReadinessOut(BaseModel):
    """Prerequisites for a run and whether each is present."""

    replay_setting: str
    replay_dir: str | None
    replay_configured: bool
    replay_present: bool
    replay_rows: int | None
    holdout_dir: str
    holdout_present: bool
    holdout_rows: int | None
    holdout_message: str
    base_checkpoint: str
    base_checkpoint_present: bool
    #: Distinct (study, field) corrections across all sealed batches; only the
    #: latest edit of a field counts.
    cumulative_corrections: int
    sealed_batches: int
    #: True when a full run (corrections + replay) can start right now.
    can_run: bool
    #: True when only the replay set is missing, so an explicit replay-free
    #: run is possible.
    can_run_without_replay: bool
    #: Problems no flag can work around (no held-out set, no base checkpoint).
    blockers: list[str]
    #: Why the replay set is unusable, if it is. Separate from `blockers`
    #: because it can be overridden with `without_replay`.
    replay_blocker: str | None
    defaults: dict
    #: The batch a run is currently working on, if any.
    running_batch_id: str | None


def _job_is_alive(job_id: str | None) -> bool:
    """Whether this process holds a running job with that id.

    The job registry is in-memory, so after a restart every "running" row is
    stale.
    """
    if not job_id:
        return False
    job = jobs.get(job_id)
    return job is not None and job.status == "running"


def _live_run(db: Session) -> RetrainRun | None:
    """Return the run actually in flight, marking stale "running" rows interrupted.

    Called on every readiness check and start, so rows left by a restart do
    not block new runs.
    """
    mark_interrupted_runs(db, _job_is_alive)
    return (
        db.query(RetrainRun)
        .filter(RetrainRun.status == "running")
        .order_by(desc(RetrainRun.id))
        .first()
    )


def _readiness(db: Session, settings: Settings) -> ReadinessOut:
    holdout = _holdout_dir(settings)
    # A missing held-out set is reported, not raised: `verify` raises when the
    # directory is absent, which is normal on a fresh deployment.
    try:
        holdout_ok, holdout_message = freeze_holdout.verify(str(holdout))
    except (FileNotFoundError, OSError, ValueError) as exc:
        holdout_ok, holdout_message = False, f"{holdout}: {exc}"
    holdout_rows = _dataset_rows(holdout)

    replay_dir = settings.retrain_replay_dir.strip()
    replay_rows = _dataset_rows(Path(replay_dir)) if replay_dir else None

    base = model_registry.active_checkpoint_name()
    base_present = (model_registry.WEIGHTS_DIR / base).is_file()

    submitted = db.query(CorrectionLog).filter(
        CorrectionLog.submitted_at.isnot(None)
    )
    cumulative = submitted.with_entities(
        CorrectionLog.study_id, CorrectionLog.field
    ).distinct().count()
    sealed_batches = (
        submitted.with_entities(CorrectionLog.batch_id).distinct().count()
    )

    blockers: list[str] = []
    if not holdout_ok:
        blockers.append(
            f"The frozen held-out set at {holdout} is unusable: {holdout_message}"
        )
    if not base_present:
        blockers.append(
            f"The checkpoint in service ({base}) is not on this machine, so "
            "there is nothing to fine-tune from."
        )

    replay_blocker = None
    if not replay_dir:
        replay_blocker = (
            f"No replay set is configured. Set {REPLAY_SETTING} to a copy of "
            "rsna_preprocessed (~8.2 GB, from the research repo)."
        )
    elif replay_rows is None:
        replay_blocker = (
            f"{REPLAY_SETTING} points at {replay_dir}, which is not there or "
            "does not hold train_metadata.csv + volumes/."
        )

    running = _live_run(db)

    return ReadinessOut(
        replay_setting=REPLAY_SETTING,
        replay_dir=replay_dir or None,
        replay_configured=bool(replay_dir),
        replay_present=replay_rows is not None,
        replay_rows=replay_rows,
        holdout_dir=str(holdout),
        holdout_present=holdout_ok,
        holdout_rows=holdout_rows,
        holdout_message=holdout_message,
        base_checkpoint=base,
        base_checkpoint_present=base_present,
        cumulative_corrections=cumulative,
        sealed_batches=sealed_batches,
        can_run=not blockers and replay_blocker is None and running is None,
        can_run_without_replay=not blockers and running is None,
        blockers=blockers,
        replay_blocker=replay_blocker,
        defaults={
            "epochs": 5,
            "lr": 1e-4,
            "batch_size": 4,
            "replay_size": 200,
            "device": "cpu",
        },
        running_batch_id=running.batch_id if running else None,
    )


@router.get("/retraining/readiness", response_model=ReadinessOut)
def get_readiness(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ReadinessOut:
    """Report whether a re-training run can start, and what is missing if not."""
    return _readiness(db, settings)


class RetrainRunOut(BaseModel):
    id: int
    batch_id: str
    job_id: str | None
    status: str
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    duration_seconds: float | None
    params: dict
    improved: bool | None
    checkpoint_name: str | None
    #: Whether the candidate file is still on disk (it awaits approval on /models).
    checkpoint_exists: bool
    checkpoint_active: bool
    before: dict | None
    after: dict | None
    n_corrections: int | None
    n_rows: int | None
    skipped: list | None
    error: str | None

    @classmethod
    def from_row(cls, row: RetrainRun, active_checkpoint: str) -> "RetrainRunOut":
        exists = bool(
            row.checkpoint_name
            and (model_registry.WEIGHTS_DIR / row.checkpoint_name).is_file()
        )
        duration = (
            (row.finished_at - row.started_at).total_seconds()
            if row.finished_at
            else None
        )
        return cls(
            id=row.id,
            batch_id=row.batch_id,
            job_id=row.job_id,
            status=row.status,
            started_at=row.started_at,
            finished_at=row.finished_at,
            duration_seconds=round(duration, 1) if duration is not None else None,
            params=row.params_json or {},
            improved=row.improved,
            checkpoint_name=row.checkpoint_name,
            checkpoint_exists=exists,
            checkpoint_active=bool(row.checkpoint_name)
            and row.checkpoint_name == active_checkpoint,
            before=_finite_only(row.before_json),
            after=_finite_only(row.after_json),
            n_corrections=row.n_corrections,
            n_rows=row.n_rows,
            skipped=row.skipped_json,
            error=row.error,
        )


@router.get("/retraining/runs", response_model=list[RetrainRunOut])
def list_runs(
    limit: int = 20,
    db: Session = Depends(get_db),
) -> list[RetrainRunOut]:
    """List re-training runs, newest first (at most 200)."""
    active = model_registry.active_checkpoint_name()
    rows = (
        db.query(RetrainRun)
        .order_by(desc(RetrainRun.started_at), desc(RetrainRun.id))
        .limit(max(1, min(limit, 200)))
        .all()
    )
    return [RetrainRunOut.from_row(row, active) for row in rows]


class RetrainRequest(BaseModel):
    """Parameters for `retrain_head`, bounded so a request cannot start an
    unreasonably long CPU run."""

    #: "all" trains on every correction submitted so far; "batch" trains on
    #: the launching batch alone (reproducible).
    scope: Literal["all", "batch"] = "all"
    epochs: int = Field(default=5, ge=1, le=20)
    lr: float = Field(default=1e-4, gt=0, le=1e-1)
    batch_size: int = Field(default=4, ge=1, le=32)
    replay_size: int = Field(default=200, ge=0, le=5000)
    seed: int = 42
    #: Run without the replay set (no guard against catastrophic forgetting).
    #: Must be requested explicitly.
    without_replay: bool = False


def _batch_or_404(db: Session, batch_id: str) -> int:
    """Corrections sealed into this batch, or 404 if there is no such batch."""
    count = db.query(CorrectionLog).filter(CorrectionLog.batch_id == batch_id).count()
    if count == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No sealed batch with id {batch_id}.",
        )
    return count


@contextmanager
def _epoch_progress(progress, epochs: int):
    """Report progress from `retrain_head`, which has no progress hook.

    `retrain_head` scores the held-out set before training, after each epoch
    and at the end, so counting `evaluate` calls tracks real progress. The
    module-level name is temporarily replaced by a counting wrapper; this is
    safe because only one run executes at a time.
    """
    original = retrain_head.evaluate
    calls = {"n": 0}
    span = epochs + 1  # scorings to expect: one per epoch, plus the final one

    def counting(*args, **kwargs):
        index = calls["n"]
        if index == 0:
            progress("Scoring the checkpoint in service on the held-out set", 10)
        else:
            progress(
                f"Scoring on the held-out set — round {index} of up to {span}",
                min(92, 12 + int(80 * index / (span + 1))),
            )
        metrics = original(*args, **kwargs)
        calls["n"] = index + 1
        if index < epochs:
            progress(
                f"Fine-tuning on CPU — epoch {index + 1} of up to {epochs}",
                min(92, 12 + int(80 * (index + 0.5) / (span + 1))),
            )
        return metrics

    retrain_head.evaluate = counting
    try:
        yield
    finally:
        retrain_head.evaluate = original


def _run_retraining(
    run_id: int,
    batch_id: str,
    settings: Settings,
    request: RetrainRequest,
    replay_dir: str | None,
    base_checkpoint: str,
    progress,
) -> None:
    """Execute one run on the job's background thread.

    Records the outcome on the `retrain_runs` row, including on failure (then
    re-raises so the job also reports the error).
    """
    session = SessionLocal()
    try:
        cumulative = request.scope == "all"
        progress(
            "Rebuilding every correction sent so far"
            if cumulative
            else "Rebuilding the corrections in this batch",
            2,
        )
        dataset_dir = _dataset_dir(settings, batch_id, cumulative)
        # batch_id=None makes `build_dataset` take every submitted correction,
        # deduped to the latest edit per (study, field) across all batches.
        build = build_dataset.build_finetune_dataset(
            session, str(dataset_dir), batch_id=None if cumulative else batch_id
        )

        run = session.get(RetrainRun, run_id)
        if run is not None:
            run.n_corrections = build.num_corrections_used
            run.n_rows = build.num_rows
            run.skipped_json = build.skipped
            session.commit()

        if build.num_rows == 0:
            raise RuntimeError(
                f"Nothing to train on: {build.num_corrections_used} correction(s) "
                f"in {'every sealed batch' if cumulative else batch_id} produced "
                "0 usable disc(s). Corrections to the "
                "eight conditions that come from the vendored SpineNet are not "
                "re-trained here, and a disc is skipped when its study has no "
                "saved mask to re-cut the crop from."
                + (f" Skipped: {build.skipped}" if build.skipped else "")
            )

        progress(
            f"{build.num_rows} corrected disc(s) rebuilt; loading the held-out set",
            8,
        )
        out_checkpoint = _candidate_checkpoint_path(batch_id, cumulative)

        with _epoch_progress(progress, request.epochs):
            result = retrain_head.retrain_head(
                # Use the checkpoint resolved at start time, so the run log
                # names the checkpoint that was actually fine-tuned.
                checkpoint_path=str(model_registry.WEIGHTS_DIR / base_checkpoint),
                dataset_dir=str(dataset_dir),
                holdout_dir=str(_holdout_dir(settings)),
                out_checkpoint=str(out_checkpoint),
                epochs=request.epochs,
                lr=request.lr,
                batch_size=request.batch_size,
                device="cpu",
                replay_dir=replay_dir,
                replay_size=request.replay_size,
                seed=request.seed,
            )

        run = session.get(RetrainRun, run_id)
        if run is not None:
            run.status = "done"
            run.finished_at = datetime.datetime.utcnow()
            run.improved = bool(result.improved)
            run.checkpoint_name = (
                Path(result.checkpoint_path).name if result.checkpoint_path else None
            )
            run.before_json = _finite_only(result.before)
            run.after_json = _finite_only(result.after)
            session.commit()

        if result.improved:
            progress(
                f"Held-out macro-F1 improved — candidate saved as "
                f"{out_checkpoint.name}, waiting for approval",
                99,
            )
        else:
            progress(
                "No held-out macro-F1 improvement — nothing was saved, and "
                "the model in service is unchanged",
                99,
            )
    except Exception as exc:
        run = session.get(RetrainRun, run_id)
        if run is not None:
            run.status = "error"
            run.finished_at = datetime.datetime.utcnow()
            run.error = f"{type(exc).__name__}: {exc}"
            session.commit()
        raise
    finally:
        session.close()


@router.post(
    "/corrections/batches/{batch_id}/retrain",
    response_model=JobOut,
    status_code=202,
    dependencies=[Depends(require_admin)],
)
def start_retrain(
    batch_id: str,
    request: RetrainRequest | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JobOut:
    """Start a re-training run launched from this batch; poll `/jobs/{id}`.

    `scope` selects every submitted correction (default) or this batch only.
    A successful run only writes a candidate checkpoint; it is never
    activated automatically.

    Returns 404 for an unknown batch, 409 when prerequisites are missing or
    another run is in progress, and 400 when the replay set is missing and
    `without_replay` was not requested. If the same batch is already running,
    its existing job is returned.
    """
    request = request or RetrainRequest()
    batch_corrections = _batch_or_404(db, batch_id)
    readiness = _readiness(db, settings)
    cumulative = request.scope == "all"

    if readiness.blockers:
        # Something other than the replay set is missing (held-out set,
        # checkpoint); no flag makes that runnable.
        raise HTTPException(status_code=409, detail=" ".join(readiness.blockers))

    replay_dir = readiness.replay_dir if readiness.replay_present else None
    if replay_dir is None and not request.without_replay:
        raise HTTPException(
            status_code=400,
            detail=(
                (readiness.replay_blocker or "")
                + " The replay set is what keeps the heads anchored to the "
                "distribution the deployed checkpoint learned; training on "
                "corrections alone is the standard way to make a model forget. "
                "Configure it, or ask for a replay-free run explicitly "
                "(without_replay=true), which is a different and weaker "
                "experiment."
            ).strip(),
        )

    with _start_lock:
        existing_job = jobs.running_for(JOB_KIND, batch_id)
        if existing_job is not None:
            # Same batch already running: return that job instead of a rival.
            return JobOut.from_job(existing_job)

        in_flight = _live_run(db)
        if in_flight is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"A re-training run on batch {in_flight.batch_id} is still "
                    "going. Head-only fine-tuning on CPU takes tens of minutes "
                    "and one run uses the whole machine, so they are taken one "
                    "at a time."
                ),
            )

        run = RetrainRun(
            batch_id=batch_id,
            status="running",
            started_at=datetime.datetime.utcnow(),
            # Expected size; replaced with the actual count after the rebuild.
            n_corrections=(
                readiness.cumulative_corrections if cumulative else batch_corrections
            ),
            params_json={
                "scope": request.scope,
                "epochs": request.epochs,
                "lr": request.lr,
                "batch_size": request.batch_size,
                "replay_size": request.replay_size if replay_dir else 0,
                "replay_dir": replay_dir,
                "seed": request.seed,
                "device": "cpu",
                "base_checkpoint": readiness.base_checkpoint,
                "holdout_dir": readiness.holdout_dir,
                "dataset_dir": str(_dataset_dir(settings, batch_id, cumulative)),
            },
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        # Pass a plain id: the request session closes after the response, and
        # the worker thread cannot use ORM instances bound to it.
        run_id = run.id

        # The job id is known only after the thread starts; the worker waits
        # until it has been written to the row.
        row_written = threading.Event()

        def work(progress) -> None:
            row_written.wait(timeout=30)
            _run_retraining(
                run_id,
                batch_id,
                settings,
                request,
                replay_dir,
                readiness.base_checkpoint,
                progress,
            )

        job = jobs.start(JOB_KIND, batch_id, work)
        run.job_id = job.id
        db.commit()
        row_written.set()

    return JobOut.from_job(job)
