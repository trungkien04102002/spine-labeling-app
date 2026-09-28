"""Patient/study listing for the patient-list page."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_db import Patient, Reader, Study
from app.routers.readers import current_reader
from app.schemas import PatientOut, StudyOut

router = APIRouter(tags=["patients"])


@router.get("/patients", response_model=list[PatientOut])
def list_patients(
    db: Session = Depends(get_db),
    reader: Reader | None = Depends(current_reader),
) -> list[PatientOut]:
    """The worklist: a room's own patients, or everyone's for the operator."""
    query = db.query(Patient)
    if reader is not None:
        query = query.filter(Patient.reader_id == reader.id)
    patients = query.order_by(Patient.id).all()
    result: list[PatientOut] = []
    for patient in patients:
        studies = (
            db.query(Study).filter_by(patient_id=patient.id).order_by(Study.id).all()
        )
        result.append(
            PatientOut(
                id=patient.id,
                name=patient.name,
                created_at=patient.created_at,
                studies=[
                    StudyOut(
                        id=s.id,
                        modality=s.modality,
                        has_volume=bool(s.volume_path),
                        created_at=s.created_at,
                    )
                    for s in studies
                ],
            )
        )
    return result
