"""Doctor corrections on their way to the model, and which model is served.

Saving a correction and handing it to the model are deliberately two steps.
Saving is the doctor fixing the record for this patient; submitting is them
choosing to contribute it as training material. Splitting them gives the doctor
an explicit, visible hand-off instead of a silent pipe from the chart into a
training set, and it gives retraining a fixed batch to work from while new
corrections keep arriving.

Submitting does not retrain anything. It queues -- a batch is picked up offline
by `app.feedback.build_dataset` + `retrain_head`, and only becomes live when
someone activates the resulting checkpoint here. That human gate is what FDA's
Predetermined Change Control Plan guidance expects of a model that changes
after deployment, and it is the reason a bad batch can never quietly reach a
patient.
"""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db import get_db
from app.feedback import model_registry
from app.models_db import CorrectionLog

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
    """One sealed hand-off: what `POST /corrections/submit` stamped in one go."""

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


@router.get("/corrections", response_model=CorrectionQueue)
def list_corrections(
    limit: int = 20,
    status: str = "all",
    db: Session = Depends(get_db),
) -> CorrectionQueue:
    """How many corrections are waiting, how many were handed over, and the latest few.

    The counts are always over the whole log; `status` narrows only `recent`.
    That matters for the operator view, where the queue and the already-sent
    history are two separate lists: asking for the newest 200 rows overall can
    return 200 sent rows and hide a waiting one, which would misreport the
    thing the queue exists to show. `status` is one of "all" (default),
    "pending" or "submitted"; anything else is treated as "all" rather than
    refused, so an older client asking for something unknown still gets a
    usable answer.
    """
    pending = db.query(CorrectionLog).filter(CorrectionLog.submitted_at.is_(None))
    submitted = db.query(CorrectionLog).filter(CorrectionLog.submitted_at.isnot(None))

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
        query = db.query(CorrectionLog)

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
    """Every sealed batch, newest first, with its size and the studies it spans.

    A batch id is the only handle that makes a past training run reproducible
    (`build_dataset --batch-id` rebuilds exactly the corrections it saw), so
    the operator view needs the ids themselves, not just a count of them. The
    study list is here because a batch is deliberately cross-patient -- it is
    every correction outstanding at the moment someone pressed send, whichever
    patient it came from -- and a count alone never shows that.
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
def submit_corrections(db: Session = Depends(get_db)) -> SubmitResult:
    """Hand every pending correction to the model as one batch.

    Stamps the rows and returns; training happens offline. Submitting with
    nothing pending is not an error -- it just reports zero, so a doctor
    pressing the button twice gets a clear answer rather than a failure.
    """
    pending = (
        db.query(CorrectionLog).filter(CorrectionLog.submitted_at.is_(None)).all()
    )
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
    return [
        CheckpointOut(**vars(info)) for info in model_registry.list_checkpoints()
    ]


@router.post("/model/activate", response_model=CheckpointOut)
def activate_model(request: ActivateRequest) -> CheckpointOut:
    """Put a checkpoint into service. Takes effect on the next inference."""
    try:
        info = model_registry.activate(request.checkpoint)
    except model_registry.UnknownCheckpoint as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CheckpointOut(**vars(info))


@router.post("/model/revert", response_model=CheckpointOut)
def revert_model() -> CheckpointOut:
    """Go back to the shipped baseline checkpoint."""
    try:
        info = model_registry.revert()
    except model_registry.UnknownCheckpoint as exc:  # baseline file went missing
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return CheckpointOut(**vars(info))
