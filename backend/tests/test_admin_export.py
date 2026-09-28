"""The operator lock, the trial export, and the per-room correction queue."""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import Base, get_db
from app.main import app
from app.models_db import CorrectionLog, Patient, Study
from app.survey_questions import REQUIRED_IDS

KEY = "phong-kham-2026"


@pytest.fixture
def env(tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: Settings(
        data_dir=str(tmp_path), admin_password=KEY
    )
    yield TestClient(app), Session
    app.dependency_overrides.clear()


def _room(client, name):
    r = client.post("/readers", json={"name": name}).json()
    return {"x-reader-id": str(r["id"])}


OPERATOR_ONLY = [
    ("get", "/readers"),
    ("get", "/survey/summary"),
    ("get", "/survey/responses"),
    ("get", "/survey/responses.csv"),
    ("get", "/trial/export.zip"),
    ("post", "/model/revert"),
]


@pytest.mark.parametrize("method,path", OPERATOR_ONLY)
def test_operator_pages_are_locked_without_the_passphrase(env, method, path):
    client, _ = env
    assert getattr(client, method)(path).status_code == 401
    assert getattr(client, method)(path, headers={"x-admin-key": "wrong"}).status_code == 401


def test_the_passphrase_opens_them(env):
    client, _ = env
    assert client.post("/admin/login", json={"password": "wrong"}).status_code == 401
    assert client.post("/admin/login", json={"password": KEY}).status_code == 200
    assert client.get("/survey/summary", headers={"x-admin-key": KEY}).status_code == 200


def test_what_a_clinician_does_needs_no_passphrase(env):
    """The lock must not get between a clinician and the tool."""
    client, _ = env
    room = _room(client, "Minh")
    assert client.get("/patients", headers=room).status_code == 200
    assert client.get("/survey/questions").status_code == 200
    answers = {qid: 4 for qid in REQUIRED_IDS}
    assert client.post("/survey/responses", json={"answers": answers}, headers=room).status_code == 201
    assert client.get("/corrections", headers=room).status_code == 200


def _pending(Session, study_id, reader_id):
    db = Session()
    patient = Patient(name="P", reader_id=reader_id)
    db.add(patient)
    db.flush()
    db.add(Study(id=study_id, patient_id=patient.id, reader_id=reader_id))
    db.add(CorrectionLog(study_id=study_id, field="L4-L5/canal_stenosis",
                         old="Moderate", new="Severe", reader_id=reader_id))
    db.commit()
    db.close()


def test_one_room_cannot_see_or_send_another_rooms_corrections(env):
    """The queue used to be app-wide: pressing Send in one room sent everyone's."""
    client, Session = env
    minh, lan = _room(client, "Minh"), _room(client, "Lan")
    _pending(Session, "a", int(minh["x-reader-id"]))
    _pending(Session, "b", int(lan["x-reader-id"]))

    assert client.get("/corrections", headers=minh).json()["pending"] == 1
    assert client.post("/corrections/submit", headers=minh).json()["submitted"] == 1
    # Lan's is still waiting, for Lan to send.
    assert client.get("/corrections", headers=lan).json()["pending"] == 1


def test_the_export_carries_every_file_and_opens_in_excel(env):
    client, Session = env
    minh = _room(client, "Minh")
    _pending(Session, "a", int(minh["x-reader-id"]))
    client.post("/survey/responses",
                json={"answers": {qid: 3 for qid in REQUIRED_IDS}, "comment": "Rất hữu ích"},
                headers=minh)

    resp = client.get("/trial/export.zip", headers={"x-admin-key": KEY})
    assert resp.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    assert {"README.txt", "readers.csv", "survey_responses.csv",
            "questions.csv", "corrections.csv"} <= set(z.namelist())

    survey = z.read("survey_responses.csv").decode("utf-8")
    # The byte-order mark is what makes Excel read Vietnamese correctly.
    assert survey.startswith("\ufeff")
    assert "Minh" in survey and "Rất hữu ích" in survey
    corrections = z.read("corrections.csv").decode("utf-8")
    assert "Minh" in corrections and "canal_stenosis" in corrections
