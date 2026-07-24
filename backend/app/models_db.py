import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base


def mark_analyzed(db: Session, study: "Study") -> None:
    """Record which series the AI just ran on (the active one).

    Inference reads a single acquisition, so the viewer can state plainly which
    one that was instead of letting a multi-series study imply the model read
    every plane.
    """
    row = (
        db.query(Series)
        .filter_by(study_id=study.id, volume_path=study.volume_path)
        .first()
    )
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
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # "ai" | "corrected"
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
