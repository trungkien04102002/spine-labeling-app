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
def list_corrections(limit: int = 20, db: Session = Depends(get_db)) -> CorrectionQueue:
    """How many corrections are waiting, how many were handed over, and the latest few."""
    pending = db.query(CorrectionLog).filter(CorrectionLog.submitted_at.is_(None))
    submitted = db.query(CorrectionLog).filter(CorrectionLog.submitted_at.isnot(None))

    batch_ids = {
        row.batch_id
        for row in submitted.with_entities(CorrectionLog.batch_id).all()
        if row.batch_id
    }

    recent = (
        db.query(CorrectionLog)
        .order_by(desc(CorrectionLog.at), desc(CorrectionLog.id))
        .limit(max(1, min(limit, 200)))
        .all()
    )

    return CorrectionQueue(
        pending=pending.count(),
        submitted=submitted.count(),
        batches=len(batch_ids),
        recent=[CorrectionOut.model_validate(c, from_attributes=True) for c in recent],
    )


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
            message="Không có chỉnh sửa nào đang chờ gửi.",
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
            f"Đã gửi {len(pending)} chỉnh sửa cho AI học (mã lô {batch_id}). "
            "Mô hình sẽ được huấn luyện lại ngoại tuyến và chỉ thay đổi khi "
            "được duyệt."
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
