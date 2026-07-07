"""Tests for the patient/study listing endpoint."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models_db import Patient, Study


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
    seed.add(Study(id="s1", patient_id=patient.id, volume_path="/data/s1/v.mha"))
    seed.add(Study(id="s2", patient_id=patient.id))  # no volume yet
    seed.commit()
    seed.close()

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_patients(client):
    resp = client.get("/patients")
    assert resp.status_code == 200

    patients = resp.json()
    assert len(patients) == 1
    p = patients[0]
    assert p["name"] == "Demo"
    assert len(p["studies"]) == 2

    by_id = {s["id"]: s for s in p["studies"]}
    assert by_id["s1"]["has_volume"] is True
    assert by_id["s2"]["has_volume"] is False
