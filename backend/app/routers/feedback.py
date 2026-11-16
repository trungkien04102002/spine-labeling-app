"""Clinician correction queue, and selection of the checkpoint in service.

Saving a correction and submitting it for training are separate steps:
saving fixes this patient's record; submitting seals pending corrections into
a fixed batch that re-training can work from while new corrections arrive.

Submitting does not retrain anything. Batches are consumed by
`app.feedback.build_dataset` and `retrain_head`, and a resulting checkpoint
grades patients only after someone activates it here (a human approval gate,
in line with FDA Predetermined Change Control Plan guidance).
"""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_db import Reader
from app.routers.readers import current_reader
from app.feedback import model_registry
from app.jsonsafe import finite_only
from app.models_db import CorrectionLog, ModelActivation

from app.routers.admin import require_admin  # noqa: E402

router = APIRouter(tags=["feedback"])


class CorrectionOut(BaseModel):
    id: int
    study_id: str
    field: str
    old: str | None
    new: str | None
    at: datetime.datetime
    submitted_at: datetime.datetime | None
    batch_id: str | None


class CorrectionQueue(BaseModel):
    pending: int
    submitted: int
    batches: int
    recent: list[CorrectionOut]


class BatchOut(BaseModel):
    """One sealed batch: the corrections stamped by one `POST /corrections/submit`."""

    batch_id: str
    sealed_at: datetime.datetime | None
    corrections: int
    studies: list[str]


class SubmitResult(BaseModel):
    batch_id: str
    submitted: int
    message: str


class CheckpointOut(BaseModel):
    name: str
    size_bytes: int
    modified_at: datetime.datetime
    is_active: bool
    is_baseline: bool
    metrics: dict | None


class ActivateRequest(BaseModel):
    checkpoint: str


class ActivationOut(BaseModel):
    """One recorded decision to change the checkpoint in service."""

    id: int
    checkpoint: str
    previous_checkpoint: str | None
    action: str
    #: None means unattributed: there is no authentication, so no user name.
    actor: str | None
    at: datetime.datetime


def _checkpoint_out(info: model_registry.CheckpointInfo) -> CheckpointOut:
    """Convert checkpoint info for HTTP, replacing NaN/inf metrics with null.

    Metrics sidecars may contain NaN for classes absent from the held-out set,
    and the browser's ``JSON.parse`` rejects bare ``NaN``.
    """
    fields = vars(info) | {"metrics": finite_only(info.metrics)}
    return CheckpointOut(**fields)


def _record_activation(
    db: Session, checkpoint: str, previous: str | None, action: str
) -> None:
    """Record a change of the serving checkpoint.

    Call only after the change succeeded, so the log never records a change
    that did not happen.
    """
    db.add(
        ModelActivation(
            checkpoint=checkpoint,
            previous_checkpoint=previous,
            action=action,
            # No authentication, so the change is recorded as unattributed.
            actor=None,
            at=datetime.datetime.utcnow(),
        )
    )
    db.commit()


@router.get("/corrections", response_model=CorrectionQueue)
def list_corrections(
    limit: int = 20,
    status: str = "all",
    db: Session = Depends(get_db),
    reader: Reader | None = Depends(current_reader),
) -> CorrectionQueue:
    """Return pending/submitted counts and the most recent corrections.

    Counts always cover the whole log (scoped to the reader room, if any);
    `status` ("all", "pending" or "submitted") filters only `recent`. Unknown
    values are treated as "all".
    """
    # In a reader room, only that room's corrections are counted.
    base = db.query(CorrectionLog)
    if reader is not None:
        base = base.filter(CorrectionLog.reader_id == reader.id)
    pending = base.filter(CorrectionLog.submitted_at.is_(None))
    submitted = base.filter(CorrectionLog.submitted_at.isnot(None))

    batch_ids = {
        row.batch_id
        for row in submitted.with_entities(CorrectionLog.batch_id).all()
        if row.batch_id
    }

    if status == "pending":
        query = pending
    elif status == "submitted":
        query = submitted
    else:
        query = base

    recent = (
        query.order_by(desc(CorrectionLog.at), desc(CorrectionLog.id))
        .limit(max(1, min(limit, 200)))
        .all()
    )

    return CorrectionQueue(
        pending=pending.count(),
        submitted=submitted.count(),
        batches=len(batch_ids),
        recent=[CorrectionOut.model_validate(c, from_attributes=True) for c in recent],
    )


@router.get("/corrections/batches", response_model=list[BatchOut])
def list_batches(db: Session = Depends(get_db)) -> list[BatchOut]:
    """List sealed batches, newest first, with their size and studies.

    A batch id is what makes a training run reproducible
    (`build_dataset --batch-id`). A batch can span several studies.
    """
    rows = (
        db.query(CorrectionLog)
        .filter(CorrectionLog.batch_id.isnot(None))
        .order_by(desc(CorrectionLog.submitted_at), desc(CorrectionLog.id))
        .all()
    )

    batches: dict[str, BatchOut] = {}
    for row in rows:
        batch = batches.get(row.batch_id)
        if batch is None:
            batches[row.batch_id] = BatchOut(
                batch_id=row.batch_id,
                sealed_at=row.submitted_at,
                corrections=1,
                studies=[row.study_id],
            )
            continue
        batch.corrections += 1
        if row.study_id not in batch.studies:
            batch.studies.append(row.study_id)

    return list(batches.values())


@router.post("/corrections/submit", response_model=SubmitResult)
def submit_corrections(
    db: Session = Depends(get_db),
    reader: Reader | None = Depends(current_reader),
) -> SubmitResult:
    """Seal all pending corrections (of the reader room, if any) into one batch.

    Only stamps the rows; no training is started. With nothing pending, returns
    `submitted=0` rather than an error.
    """
    query = db.query(CorrectionLog).filter(CorrectionLog.submitted_at.is_(None))
    if reader is not None:
        query = query.filter(CorrectionLog.reader_id == reader.id)
    pending = query.all()
    if not pending:
        return SubmitResult(
            batch_id="",
            submitted=0,
            message="No corrections are waiting to be sent.",
        )

    batch_id = f"batch-{datetime.datetime.utcnow():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    now = datetime.datetime.utcnow()
    for correction in pending:
        correction.submitted_at = now
        correction.batch_id = batch_id
    db.commit()

    return SubmitResult(
        batch_id=batch_id,
        submitted=len(pending),
        message=(
            f"Sent {len(pending)} correction{'' if len(pending) == 1 else 's'} "
            f"as batch {batch_id}. Re-training runs offline, and the new model "
            "version has to be reviewed before it grades anyone."
        ),
    )


@router.get("/model/versions", response_model=list[CheckpointOut])
def list_model_versions() -> list[CheckpointOut]:
    """Checkpoints available to serve, baseline first."""
    return [_checkpoint_out(info) for info in model_registry.list_checkpoints()]


@router.post("/model/activate", response_model=CheckpointOut, dependencies=[Depends(require_admin)])
def activate_model(
    request: ActivateRequest, db: Session = Depends(get_db)
) -> CheckpointOut:
    """Put a checkpoint into service; it takes effect on the next inference.

    Recorded in ``model_activations``. Returns 404 for an unknown checkpoint.
    """
    previous = model_registry.active_checkpoint_name()
    try:
        info = model_registry.activate(request.checkpoint)
    except model_registry.UnknownCheckpoint as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _record_activation(db, info.name, previous, "activate")
    return _checkpoint_out(info)


@router.post("/model/revert", response_model=CheckpointOut, dependencies=[Depends(require_admin)])
def revert_model(db: Session = Depends(get_db)) -> CheckpointOut:
    """Revert to the baseline checkpoint; recorded like any activation.

    Returns 500 if the baseline file is missing.
    """
    previous = model_registry.active_checkpoint_name()
    try:
        info = model_registry.revert()
    except model_registry.UnknownCheckpoint as exc:  # baseline file went missing
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    _record_activation(db, info.name, previous, "revert")
    return _checkpoint_out(info)


@router.get("/model/activations", response_model=list[ActivationOut])
def list_model_activations(
    limit: int = 20, db: Session = Depends(get_db)
) -> list[ActivationOut]:
    """List recorded changes of the serving checkpoint, newest first.

    An empty list means the baseline checkpoint has never been replaced.
    """
    rows = (
        db.query(ModelActivation)
        .order_by(desc(ModelActivation.at), desc(ModelActivation.id))
        .limit(max(1, min(limit, 200)))
        .all()
    )
    return [ActivationOut.model_validate(r, from_attributes=True) for r in rows]
