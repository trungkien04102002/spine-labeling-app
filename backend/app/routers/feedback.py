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


class ActivationOut(BaseModel):
    """One recorded decision to change the checkpoint in service."""

    id: int
    checkpoint: str
    previous_checkpoint: str | None
    action: str
    #: None == unattributed. This build has no sign-in, so there is no name to
    #: report; the UI says so rather than implying the record names someone.
    actor: str | None
    at: datetime.datetime


def _checkpoint_out(info: model_registry.CheckpointInfo) -> CheckpointOut:
    """A checkpoint on its way out over HTTP, with its numbers made JSON-safe.

    The sidecar written beside a retrained checkpoint can hold NaN: a class
    with no examples in the held-out set scores NaN on purpose, so it can be
    left out of the macro average rather than counted as zero. `json.dumps`
    emits that as the bare token `NaN`, which `JSON.parse` rejects -- and it
    rejects the whole response, so one absent measurement inside one
    checkpoint stops `/models` from loading at all instead of leaving one cell
    blank. `app.jsonsafe.finite_only` turns it into `null`, which is what a
    measurement that was not made actually means, and is the same rule the
    re-training run log applies to the same numbers.
    """
    fields = vars(info) | {"metrics": finite_only(info.metrics)}
    return CheckpointOut(**fields)


def _record_activation(
    db: Session, checkpoint: str, previous: str | None, action: str
) -> None:
    """Write down that someone changed what grades patients, and from what.

    Called after the pointer has actually moved, so the log never claims a
    change that did not happen.
    """
    db.add(
        ModelActivation(
            checkpoint=checkpoint,
            previous_checkpoint=previous,
            action=action,
            # No authentication in this build; recorded as unattributed rather
            # than attributed to an invented user.
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
    # In a room, the queue is that room's: a clinician's "waiting to be sent"
    # must not count, or send, another clinician's corrections.
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
def submit_corrections(
    db: Session = Depends(get_db),
    reader: Reader | None = Depends(current_reader),
) -> SubmitResult:
    """Hand every pending correction to the model as one batch.

    Stamps the rows and returns; training happens offline. Submitting with
    nothing pending is not an error -- it just reports zero, so a doctor
    pressing the button twice gets a clear answer rather than a failure.
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
    """Put a checkpoint into service. Takes effect on the next inference.

    The change is recorded in ``model_activations`` once it has taken: what
    was in service before, what is now, and when. A refused activation writes
    nothing, because nothing changed.
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
    """Go back to the shipped baseline checkpoint.

    Recorded like any other activation: reverting decides what the next
    patient is graded by just as much as approving a candidate does.
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
    """Every recorded decision to change the serving checkpoint, newest first.

    Empty is a meaningful answer, not a missing one: it means nothing has been
    switched on this server since the record started -- the baseline the app
    shipped with is still what grades patients.
    """
    rows = (
        db.query(ModelActivation)
        .order_by(desc(ModelActivation.at), desc(ModelActivation.id))
        .limit(max(1, min(limit, 200)))
        .all()
    )
    return [ActivationOut.model_validate(r, from_attributes=True) for r in rows]
