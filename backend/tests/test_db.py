from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models_db import Annotation, CorrectionLog, Patient, Study


def _make_sqlite_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine)
    return session_local()


def test_patient_study_annotation_roundtrip():
    db = _make_sqlite_session()

    patient = Patient(name="John Doe")
    db.add(patient)
    db.commit()
    db.refresh(patient)
    assert patient.id is not None
    assert patient.created_at is not None

    study = Study(
        id="study-uuid-1",
        patient_id=patient.id,
        modality="MRI",
        volume_path="/data/vol.npy",
        display_path="/data/vol_display.png",
    )
    db.add(study)
    db.commit()

    annotation = Annotation(
        study_id=study.id,
        version=1,
        kind="ai",
        payload_json={"levels": ["L4-L5"]},
        mask_path="/data/mask.npy",
    )
    db.add(annotation)
    db.commit()

    correction = CorrectionLog(
        study_id=study.id,
        field="severity",
        old="mild",
        new="severe",
    )
    db.add(correction)
    db.commit()

    fetched_patient = db.query(Patient).one()
    assert fetched_patient.name == "John Doe"

    fetched_study = db.query(Study).one()
    assert fetched_study.id == "study-uuid-1"
    assert fetched_study.patient_id == patient.id
    assert fetched_study.modality == "MRI"
    assert fetched_study.volume_path == "/data/vol.npy"

    fetched_annotation = db.query(Annotation).one()
    assert fetched_annotation.study_id == study.id
    assert fetched_annotation.kind == "ai"
    assert fetched_annotation.payload_json == {"levels": ["L4-L5"]}

    fetched_correction = db.query(CorrectionLog).one()
    assert fetched_correction.study_id == study.id
    assert fetched_correction.field == "severity"
    assert fetched_correction.old == "mild"
    assert fetched_correction.new == "severe"

    db.close()
