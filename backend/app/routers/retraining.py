"""Running one re-training batch from the operator page, and the log of runs.

The trigger is a button; the gate is not. A run here rebuilds one sealed batch
of corrections, fine-tunes the heads of the checkpoint currently in service,
scores the result on the frozen held-out set, and -- only if held-out macro-F1
improves -- writes a **candidate** checkpoint beside the baseline. It never
touches the ``ACTIVE`` pointer, never reloads the serving model, and never
changes what the next patient is graded by. That decision still belongs to a
person on ``/models``, which is where the thesis's claim about this loop
actually lives: in the approval step, not in the absence of a button.

A run trains on **every correction sent so far** by default, not only the
batch it was launched from. `build_dataset` supports both, and per-batch alone
is the wrong default for a loop that runs more than once: round two would never
see round one's corrections in its training data, so each round chases the
newest edits and lets the earlier ones decay. The replay set does not cover
that gap either -- those discs are original RSNA, so they anchor the model to
the *original* distribution, not to what the doctors have said since. Per-batch
stays available because it is what makes a past run reproducible.

Three more things this module is careful about:

* **It calls `app.feedback.build_dataset` and `app.feedback.retrain_head`; it
  does not reimplement them.** Those two modules are the method the thesis
  describes, including the guard that discards a checkpoint which does not
  improve. A second, "convenient" copy of that logic behind an HTTP endpoint
  would be the thing that quietly drifts from what the report claims.
* **The replay set is required unless you say otherwise, out loud.** It is
  ~8.2 GB of original discs from the research repo (`RETRAIN_REPLAY_DIR`).
  Without it, training on a few dozen corrections is the textbook way to make
  a model forget, so a replay-free run is offered only as an explicitly
  labelled, deliberately different experiment -- never as the silent default.
* **One run at a time, and every run is recorded.** Head-only fine-tuning on
  CPU takes tens of minutes and saturates the box; two at once would fight for
  the same CPU and the same output paths. Every attempt lands in
  ``retrain_runs`` whether it succeeded, found no improvement, or failed.
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

#: The environment variable behind `Settings.retrain_replay_dir`, named in the
#: UI so an operator can act on "not configured" without reading the source.
REPLAY_SETTING = "RETRAIN_REPLAY_DIR"

#: Serialises the check-then-start section. Two requests arriving together
#: would otherwise both find no run in flight and both start one.
_start_lock = threading.Lock()


# --- Where things live -----------------------------------------------------


def _holdout_dir(settings: Settings) -> Path:
    """The frozen held-out set that every before/after number is measured on."""
    return Path(settings.data_dir) / "holdout_frozen"


def _dataset_dir(settings: Settings, batch_id: str, cumulative: bool) -> Path:
    """Where a run's corrections are rebuilt into.

    Keyed by the batch the run was launched from, because that pins the moment
    in time; the `-all` suffix keeps a cumulative rebuild (everything sent up
    to that moment) from overwriting the per-batch one, which holds different
    data under the same name.
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
    """Drop NaN/inf from a metrics dict before it becomes JSON.

    `retrain_head.evaluate` reports NaN on purpose -- a class absent from the
    held-out set scores NaN rather than 0, so it can be left out of the macro
    average instead of dragging it down. NaN is not valid JSON, though: it
    survives `json.dumps` as the bare token `NaN`, which `JSON.parse` in the
    browser refuses, taking the whole run log down with it. So a measurement
    that does not exist is written as null, which is what it means.

    The rule itself lives in `app.jsonsafe` so that every endpoint serving
    these numbers -- the run log here, the checkpoint list on `/models` --
    applies the same one, rather than each growing its own.
    """
    if not metrics:
        return metrics
    return finite_only(metrics)


def _candidate_checkpoint_path(batch_id: str, cumulative: bool) -> Path:
    """A free filename for this run's candidate, never overwriting an old one.

    A second run from the same batch (other parameters, the other scope, more
    corrections since) is a legitimate thing to do, and silently replacing the
    checkpoint the first one produced would destroy something a person may
    still be about to approve on `/models`. The name carries the scope so two
    candidates from one batch are not mistaken for each other.
    """
    weights = model_registry.WEIGHTS_DIR
    stem = f"{batch_id}-all" if cumulative else batch_id
    candidate = weights / f"{stem}.pth"
    attempt = 2
    while candidate.exists():
        candidate = weights / f"{stem}-run{attempt}.pth"
        attempt += 1
    return candidate


# --- Readiness -------------------------------------------------------------


class ReadinessOut(BaseModel):
    """What a run needs, and which of those things this machine actually has."""

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
    #: Distinct (study, field) corrections across every sealed batch -- what a
    #: cumulative run would train on. Lower than the raw count when a doctor
    #: corrected the same grade twice: only the latest edit counts.
    cumulative_corrections: int
    sealed_batches: int
    #: True when a full run (corrections + replay) can start right now.
    can_run: bool
    #: True when the only thing missing is the replay set, i.e. a deliberately
    #: weaker, replay-free run is possible if someone asks for it explicitly.
    can_run_without_replay: bool
    #: Things no flag can work around: no held-out set, no checkpoint to
    #: fine-tune from.
    blockers: list[str]
    #: Why the replay set cannot be used, if it cannot. Kept apart from
    #: `blockers` because it is the one gap a person may knowingly accept.
    replay_blocker: str | None
    defaults: dict
    #: The batch a run is currently working on, if any.
    running_batch_id: str | None


def _job_is_alive(job_id: str | None) -> bool:
    """Whether this process still holds a running job for that id.

    A run only ever starts inside the server process, so its job is in this
    registry for as long as it is really going. After a restart the registry is
    empty and every "running" row is, correctly, stale.
    """
    if not job_id:
        return False
    job = jobs.get(job_id)
    return job is not None and job.status == "running"


def _live_run(db: Session) -> RetrainRun | None:
    """The run genuinely in flight, closing out any row that only claims to be.

    Called on every readiness check and before every start, so a row left over
    by a restart heals the first time the page is opened rather than refusing
    runs forever.
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
    # A missing or unreadable held-out set is a state this page exists to
    # report, not a crash. `verify` raises when the directory is not there at
    # all -- which is exactly what a fresh deployment looks like, since
    # `data/` is gitignored and does not travel with the code.
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
    """Whether a run can start, and precisely what is missing when it cannot."""
    return _readiness(db, settings)


# --- The run log -----------------------------------------------------------


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
    #: The candidate is a file on disk until someone approves it on /models.
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
    """Every run attempted on this machine, newest first."""
    active = model_registry.active_checkpoint_name()
    rows = (
        db.query(RetrainRun)
        .order_by(desc(RetrainRun.started_at), desc(RetrainRun.id))
        .limit(max(1, min(limit, 200)))
        .all()
    )
    return [RetrainRunOut.from_row(row, active) for row in rows]


# --- Starting a run --------------------------------------------------------


class RetrainRequest(BaseModel):
    """Everything `retrain_head` takes, with its own defaults.

    Bounds are here so a typo in a request cannot start a run that would take
    days on CPU, and so the recorded parameters are always ones that were
    actually usable.
    """

    #: "all" (default) trains on every correction submitted so far, so each
    #: round has to satisfy everything the doctors have said to date rather
    #: than only the newest batch. "batch" trains on the launching batch alone,
    #: which is what makes a past run exactly reproducible.
    scope: Literal["all", "batch"] = "all"
    epochs: int = Field(default=5, ge=1, le=20)
    lr: float = Field(default=1e-4, gt=0, le=1e-1)
    batch_size: int = Field(default=4, ge=1, le=32)
    replay_size: int = Field(default=200, ge=0, le=5000)
    seed: int = 42
    #: Run WITHOUT the replay set. A different, weaker experiment: the guard
    #: against catastrophic forgetting is gone. Never assumed, always asked for.
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
    """Report real stages out of `retrain_head`, which has no progress hook.

    `retrain_head.retrain_head()` scores the held-out set once before training,
    once after every epoch, and once at the end -- so counting those calls is
    exactly the run's real progress, and costs nothing. The function is
    observed by swapping the module-level name for a counting wrapper around
    it, and restoring it afterwards; its behaviour is untouched (it is thesis
    surface and must not be edited), and the single-run lock means no two of
    these overlap. The alternative was a bar that moves on a timer, which
    would be a lie about a run that takes tens of minutes.
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
    """The whole run, on the job's background thread.

    Writes the outcome onto the `retrain_runs` row exactly once, at the end --
    including when it fails, so a crashed run leaves a record rather than a
    row stuck at "running". Then re-raises, so the job reports an error too.
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
                # The checkpoint resolved when the run was started, not
                # whichever one is in service by the time the thread gets here:
                # the run log names one checkpoint, and it has to be the one
                # that was actually fine-tuned.
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
    """Start one re-training run on this batch and return a job to poll.

    The answer is a `JobOut` polled at `/jobs/{id}`, the same mechanism full
    grading uses -- there is one job system in this app, not two. Everything
    that can be checked up front is checked here, so an impossible request
    fails immediately with a real status code instead of becoming a job that
    dies a minute later.

    `scope` decides what it trains on: every correction sent so far (the
    default) or this batch alone. The batch id is recorded either way -- it is
    where the run was launched from, and two runs with the same batch id and
    different scopes are otherwise indistinguishable in the log.

    What this never does: activate anything. A successful run leaves a
    candidate file beside the baseline and a row in the run log; the model
    serving patients is the same one as before, until a person says otherwise
    on `/models`.
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
            # Same batch, already in flight: hand back the run that is running
            # rather than starting a rival one on the same CPU and paths.
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
            # Replaced with what the rebuild actually used once it has run;
            # this is the expected size, so a row is never blank while running.
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
        # Plain int, not the ORM object: the request's session is closed once
        # the response goes out, and a background thread touching an expired
        # instance from a closed session raises instead of running.
        run_id = run.id

        # The row has to be complete before the worker touches it: the job id
        # is only known once the thread is already running, so the worker waits
        # for this request to finish writing rather than racing it.
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
