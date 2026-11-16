import datetime
from typing import Callable

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base


def active_series(db: Session, study: "Study") -> "Series | None":
    """The series row the study currently points at, if it has one.

    Returns ``None`` for studies without series rows (legacy uploads); their
    volume still works but its plane is unknown.
    """
    return (
        db.query(Series)
        .filter_by(study_id=study.id, volume_path=study.volume_path)
        .first()
    )


def grading_series(db: Session, study: "Study") -> "Series | None":
    """The series the grading models read: the study's sagittal one.

    The models were trained on (9, 112, 224) sagittal crops, so an axial stack
    would yield confident but meaningless grades. Inference therefore reads the
    first sagittal series regardless of which one is being viewed; rows are
    stored in reading order, so sagittal T2 comes first.
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
    """Record which series inference just read, so the viewer can label it."""
    row = grading_series(db, study) or active_series(db, study)
    if row is not None:
        study.analyzed_series_id = row.id



class Reader(Base):
    """One clinician's room, isolating their studies, edits and survey answers.

    Not an account. The 4-digit PIN only prevents entering a colleague's room
    by mistake; it is not access control (the API trusts X-Reader-Id).
    """

    __tablename__ = "readers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Normalised name: case- and whitespace-insensitive, but diacritics are kept,
    # because two names that differ only in accents can be different people.
    key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    # Code carried by the room's personal link (/?phong=<code>). Unique, not secret.
    code: Mapped[str | None] = mapped_column(String(16), nullable=True, unique=True)
    # "salt$pbkdf2-hex" of the room's 4-digit PIN; None until one is set.
    pin_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )

class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Owning room; NULL for shared sample studies and rows created before rooms.
    reader_id: Mapped[int | None] = mapped_column(
        ForeignKey("readers.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )


class Study(Base):
    __tablename__ = "studies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Owning room; NULL for shared sample studies and rows created before rooms.
    reader_id: Mapped[int | None] = mapped_column(
        ForeignKey("readers.id"), nullable=True
    )
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), nullable=False)
    modality: Mapped[str] = mapped_column(String(32), default="MRI")
    volume_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    display_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Series inference last ran on (it reads one series, not all of them).
    analyzed_series_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    # The clinician's free-text conclusion for this scan.
    doctor_conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    doctor_conclusion_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
    )


class Series(Base):
    """One DICOM series (one acquisition) inside a study.

    Series (e.g. sagittal T1/T2, axial T2) have different geometry and cannot be
    stacked into one volume. ``Study.volume_path`` / ``Study.display_path``
    point at the currently active series.
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
    # "ai" (model output) | "corrected" (clinician grade edit) | "mask"
    # (clinician segmentation edit). `mask_path` is per version: a mask edit
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
    # Owning room; NULL for shared sample studies and rows created before rooms.
    reader_id: Mapped[int | None] = mapped_column(
        ForeignKey("readers.id"), nullable=True
    )
    study_id: Mapped[str] = mapped_column(ForeignKey("studies.id"), nullable=False)
    field: Mapped[str] = mapped_column(String(128), nullable=False)
    old: Mapped[str | None] = mapped_column(Text, nullable=True)
    new: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    # Corrections are logged on save but only join a training batch when
    # explicitly submitted, giving an explicit hand-off and a stable batch for
    # re-training while new corrections keep arriving.
    submitted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class RetrainRun(Base):
    """One re-training run started from the operator page, and its outcome.

    Provides provenance for candidate checkpoints: source batch, scope
    (``params_json["scope"]``: that batch only or all submitted corrections),
    parameters, and held-out metrics before and after.

    ``status`` is ``running`` | ``done`` | ``error`` | ``interrupted``.
    ``done`` with ``improved is False`` and no ``checkpoint_name`` is a normal
    outcome: ``retrain_head`` only writes a checkpoint when held-out macro-F1
    improves. ``interrupted`` marks rows whose in-memory job no longer exists
    (see ``mark_interrupted_runs``).
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
    #: All run inputs verbatim: epochs, lr, batch size, replay dir/size, base
    #: checkpoint, dataset and held-out directories.
    params_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: None while running; False = ran fine, held-out macro-F1 did not improve.
    improved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: Name of the candidate checkpoint written, if any. Never activated here.
    checkpoint_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: Corrections in the batch vs. disc rows built from them (they differ:
    #: only three of the eleven conditions are re-trained).
    n_corrections: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skipped_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ModelActivation(Base):
    """Audit record of a human decision to change or restore the active checkpoint.

    The model only changes when a person activates a checkpoint; reverts are
    recorded the same way. ``actor`` is ``None`` (unattributed) because the app
    has no authentication.
    """

    __tablename__ = "model_activations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: The checkpoint put into service by this decision.
    checkpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Checkpoint in service immediately before. Equal to `checkpoint` when the
    #: active one was re-activated; that is still recorded.
    previous_checkpoint: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    #: "activate" | "revert": the same operation, recorded with its intent.
    action: Mapped[str] = mapped_column(String(16), default="activate")
    #: None == unattributed (no authentication).
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )


def mark_interrupted_runs(db: Session, is_alive: "Callable[[str | None], bool]") -> int:
    """Mark "running" rows whose job no longer exists as interrupted.

    Jobs live in memory, so a running row without a live job (server restart,
    worker death) will never finish and would otherwise block later runs.
    `is_alive(job_id)` must check the actual job: a blanket ``False`` would mark
    live runs as interrupted when another process (e.g. tests) opens the same
    database. Returns the number of rows closed.
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


class SurveyResponse(Base):
    """One clinician's answers to the questionnaire in app/survey_questions.py.

    Answers are stored as {question_id: 1..5} so questions can change without a
    schema change; question text lives in code. ``clinical_mean`` is stored so
    reported numbers do not shift if the question set changes later.
    """

    __tablename__ = "survey_response"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Owning room; NULL for shared sample studies and rows created before rooms.
    reader_id: Mapped[int | None] = mapped_column(
        ForeignKey("readers.id"), nullable=True
    )
    # Optional, so clinicians can answer anonymously.
    respondent: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    answers_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    clinical_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    submitted_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
