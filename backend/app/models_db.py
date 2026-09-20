import datetime
from typing import Callable

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base


def active_series(db: Session, study: "Study") -> "Series | None":
    """The series row the study currently points at, if it has one.

    Returns ``None`` for studies uploaded before series tracking existed (their
    volume still works; we just cannot say which plane it is).
    """
    return (
        db.query(Series)
        .filter_by(study_id=study.id, volume_path=study.volume_path)
        .first()
    )


def grading_series(db: Session, study: "Study") -> "Series | None":
    """The series the grading models read: the study's sagittal one.

    The models take (9, 112, 224) sagittal crops -- the RSNA preprocessing
    convention they were trained on -- so an axial stack would yield confident
    but meaningless grades. Inference therefore always reads the sagittal
    series, independently of which one the doctor happens to be viewing; rows
    are stored in reading order, so sagittal T2 comes first.
    """
    rows = db.query(Series).filter_by(study_id=study.id).order_by(Series.id).all()
    for row in rows:
        if row.orientation == "sagittal":
            return row
    return None


def grading_volume_path(db: Session, study: "Study") -> str:
    """Volume path inference should run on (falls back to the study's own)."""
    row = grading_series(db, study)
    return row.volume_path if row is not None else study.volume_path


def mark_analyzed(db: Session, study: "Study") -> None:
    """Record which series the AI just read, so the viewer can name it.

    Inference reads one acquisition, not every plane in the study; flagging the
    exact row keeps the series picker from implying otherwise.
    """
    row = grading_series(db, study) or active_series(db, study)
    if row is not None:
        study.analyzed_series_id = row.id


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )


class Study(Base):
    __tablename__ = "studies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), nullable=False)
    modality: Mapped[str] = mapped_column(String(32), default="MRI")
    volume_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    display_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Which series inference last ran on, so the UI can state plainly which
    # acquisition the AI actually read (it reads one, not all of them).
    analyzed_series_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )


class Series(Base):
    """One DICOM series (one acquisition) inside a study.

    A lumbar MRI study is read across several series -- typically sagittal T1,
    sagittal T2 and axial T2 -- which are separate acquisitions with different
    geometry, so they cannot be stacked into one volume. Each gets a row here;
    ``Study.volume_path`` / ``Study.display_path`` point at whichever series is
    currently active, which is what inference and the viewer operate on.
    """

    __tablename__ = "series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    study_id: Mapped[str] = mapped_column(ForeignKey("studies.id"), nullable=False)
    # DICOM SeriesInstanceUID; synthetic for MHA/NIfTI uploads (no series concept).
    series_uid: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # "sagittal" | "axial" | "coronal" | "unknown" -- from ImageOrientationPatient.
    orientation: Mapped[str] = mapped_column(String(16), default="unknown")
    volume_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    display_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    num_slices: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    study_id: Mapped[str] = mapped_column(ForeignKey("studies.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # "ai" (what the model produced) | "corrected" (a doctor's grade edit) |
    # "mask" (a doctor's segmentation edit). `mask_path` is per version: each
    # row points at the file holding *that* version's labelmap, so a mask edit
    # archives the old file and repoints the rows that referred to it.
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    mask_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )


class CorrectionLog(Base):
    __tablename__ = "correction_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    study_id: Mapped[str] = mapped_column(ForeignKey("studies.id"), nullable=False)
    field: Mapped[str] = mapped_column(String(128), nullable=False)
    old: Mapped[str | None] = mapped_column(Text, nullable=True)
    new: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    # A correction is captured the moment a doctor saves, but it only enters a
    # training batch once someone submits it. Keeping "captured" and
    # "submitted" apart means the doctor gets an explicit hand-off ("these N
    # went to the model") instead of silently feeding a training set, and it
    # gives the retraining side a stable batch to reason about even when
    # corrections keep arriving.
    submitted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class RetrainRun(Base):
    """One re-training run started from the operator page, and how it ended.

    A run is the missing half of the audit trail: the correction log says what
    a doctor changed, ``/models`` says which checkpoint is in service, and
    nothing in between recorded that a run happened at all -- which batch it
    was launched from, whether it trained on that batch alone or on every
    correction sent so far (``params_json["scope"]``), with what parameters,
    whether a candidate came out of it, and what the held-out numbers were
    before and after. Scope belongs in the record because two runs launched
    from one batch with different scopes saw different data. Without that row
    a candidate checkpoint appearing in ``models/weights/`` has no provenance,
    and a run that produced nothing leaves no trace that it was ever tried.

    "Produced nothing" is a normal outcome, not a failure: ``retrain_head``
    refuses to write a checkpoint unless held-out macro-F1 improves, so
    ``status == "done"`` with ``improved is False`` and no ``checkpoint_name``
    is a successful run that honestly found no improvement. ``status`` is
    ``running`` | ``done`` | ``error`` | ``interrupted``; the last one is
    stamped at startup on rows left running by a server that went away,
    because an in-memory job does not survive a restart and a row stuck at
    "running" forever would block every later run.
    """

    __tablename__ = "retrain_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The in-memory job that carried it, for polling while it runs.
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    #: Everything the run was given: epochs, lr, batch size, replay dir/size,
    #: the checkpoint fine-tuned from, the dataset and held-out directories.
    #: Stored verbatim so a past run can be re-read rather than reconstructed.
    params_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: None while running; False = ran fine, held-out macro-F1 did not improve.
    improved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: Name of the candidate checkpoint written, if any. Never activated here.
    checkpoint_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: Corrections the batch held, and the disc rows actually rebuilt from them
    #: (they differ: eight of the eleven conditions are not re-trained here).
    n_corrections: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skipped_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ModelActivation(Base):
    """One decision to change (or restore) the checkpoint that grades patients.

    The whole claim this app makes about its feedback loop is that the model
    only ever changes because a person decided it should. Until this table
    existed, that decision left no trace: ``POST /model/activate`` moved a
    one-line ``ACTIVE`` pointer and nothing recorded that anyone had moved it,
    when, or away from what -- so "a human approved this" was an assertion
    about the UI, not something the system could show afterwards.

    A revert is recorded the same way, because going back to the baseline is
    an activation decision like any other: it changes what the next patient is
    graded by, and a loop that logs only the optimistic half of its decisions
    is not an audit trail.

    ``actor`` is honest about what the app knows. There is no sign-in here --
    a deliberate demo posture, not an oversight -- so it is ``None``, meaning
    "unattributed", rather than a name this code would have had to invent. If
    authentication is ever added, the column is already where the identity
    goes and old rows stay truthfully blank.
    """

    __tablename__ = "model_activations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: The checkpoint put into service by this decision.
    checkpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    #: What was in service immediately before it. Equal to `checkpoint` when
    #: someone re-activated what was already running -- still a decision, and
    #: still recorded, because "nothing happened" is itself worth being able
    #: to show.
    previous_checkpoint: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    #: "activate" | "revert" -- the same operation, but the intent differs and
    #: only the record can preserve which one a person believed they made.
    action: Mapped[str] = mapped_column(String(16), default="activate")
    #: None == unattributed: this build has no authentication. See above.
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )


def mark_interrupted_runs(db: Session, is_alive: "Callable[[str | None], bool]") -> int:
    """Close out runs that claim to be running but have nothing working on them.

    Jobs live in memory, and a run only ever starts inside the server process,
    so a "running" row whose job this process does not hold is a row nothing
    will ever finish -- the server was restarted, or the worker died between
    the job ending and the row being written. Saying so is both honest and
    necessary: a stuck row would otherwise refuse every later run for as long
    as the database lives.

    `is_alive` is asked about each row's `job_id`, which is what keeps this
    from closing out a run that is genuinely in flight. It must never be a
    blanket "no": this used to run at startup against every running row, and a
    second process opening the same database (the test suite does) stamped a
    live run as interrupted while it was still training.
    """
    stale = [
        run
        for run in db.query(RetrainRun).filter(RetrainRun.status == "running").all()
        if not is_alive(run.job_id)
    ]
    for run in stale:
        run.status = "interrupted"
        run.finished_at = datetime.datetime.utcnow()
        run.error = (
            "Nothing was working on this run any more -- the server was "
            "restarted, or the run died without recording an outcome. Nothing "
            "was saved and nothing was activated."
        )
    if stale:
        db.commit()
    return len(stale)
