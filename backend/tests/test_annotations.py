"""Tests for saving versioned corrections (PUT /studies/{id}/annotations)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models_db import Annotation, CorrectionLog, Patient, Study


def _infer_payload(study_id="s1", canal_severity="Normal/Mild"):
    return {
        "study_id": study_id,
        "segmentation": {"mask_uri": f"/studies/{study_id}/mask.nii.gz", "labels": {}},
        "grading": [
            {
                "level": "L4-L5",
                "condition": "canal_stenosis",
                "severity": canal_severity,
                "score": 0.9,
                "bbox": [10, 1, 2, 3, 4],
                "heatmap_uri": None,
            }
        ],
        "model_version": "fake-1.0",
    }


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    seed = TestingSession()
    patient = Patient(name="Demo")
    seed.add(patient)
    seed.commit()
    seed.refresh(patient)
    seed.add(Study(id="s1", patient_id=patient.id))
    # A v0 AI annotation to correct from.
    seed.add(
        Annotation(
            study_id="s1",
            version=0,
            kind="ai",
            payload_json=_infer_payload(canal_severity="Normal/Mild"),
            mask_path="/data/s1/mask.nii.gz",
        )
    )
    seed.commit()
    seed.close()

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    yield TestClient(app), TestingSession
    app.dependency_overrides.clear()


def test_put_creates_new_corrected_version(client):
    test_client, TestingSession = client
    edited = _infer_payload(canal_severity="Severe")  # doctor changed the grade

    resp = test_client.put("/studies/s1/annotations", json=edited)
    assert resp.status_code == 200
    assert resp.json()["grading"][0]["severity"] == "Severe"

    db = TestingSession()
    anns = db.query(Annotation).filter_by(study_id="s1").order_by(Annotation.version).all()
    assert [a.version for a in anns] == [0, 1]
    assert anns[1].kind == "corrected"
    # Mask path carried over from the prior version (no mask edit here).
    assert anns[1].mask_path == "/data/s1/mask.nii.gz"
    db.close()


def test_put_logs_severity_diffs(client):
    test_client, TestingSession = client
    test_client.put("/studies/s1/annotations", json=_infer_payload(canal_severity="Severe"))

    db = TestingSession()
    logs = db.query(CorrectionLog).filter_by(study_id="s1").all()
    assert len(logs) == 1
    assert logs[0].field == "L4-L5/canal_stenosis"
    assert logs[0].old == "Normal/Mild"
    assert logs[0].new == "Severe"
    db.close()


def test_put_no_change_logs_nothing(client):
    test_client, TestingSession = client
    test_client.put("/studies/s1/annotations", json=_infer_payload(canal_severity="Normal/Mild"))

    db = TestingSession()
    assert db.query(CorrectionLog).filter_by(study_id="s1").count() == 0
    # Still creates a new version even with no diffs.
    assert db.query(Annotation).filter_by(study_id="s1").count() == 2
    db.close()


def test_get_latest_returns_corrected(client):
    test_client, _ = client
    test_client.put("/studies/s1/annotations", json=_infer_payload(canal_severity="Moderate"))

    resp = test_client.get("/studies/s1/annotation")
    assert resp.status_code == 200
    assert resp.json()["grading"][0]["severity"] == "Moderate"


def test_put_unknown_study_404(client):
    test_client, _ = client
    resp = test_client.put("/studies/nope/annotations", json=_infer_payload("nope"))
    assert resp.status_code == 404
