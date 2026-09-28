"""Rooms: each clinician's studies, edits and answers stay their own."""

from pathlib import Path

import numpy as np
import pytest
import SimpleITK as sitk
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import Base, get_db
from app.main import app
from app.models_db import Annotation, CorrectionLog, Patient, Series, Study


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
        data_dir=str(tmp_path), sample_studies="VAL-*"
    )
    yield TestClient(app), Session, tmp_path
    app.dependency_overrides.clear()


def _join(client, name):
    return client.post("/readers", json={"name": name}).json()


def _as(reader):
    return {"x-reader-id": str(reader["id"])}


def test_the_same_name_returns_to_the_same_room(env):
    client, _, _ = env
    first = _join(client, "Minh")
    again = _join(client, "  MINH ")
    assert again["id"] == first["id"]
    assert first["created"] and not again["created"]
    assert _join(client, "Lan")["id"] != first["id"]


def test_a_room_sees_only_its_own_worklist(env):
    client, _, _ = env
    minh, lan = _join(client, "Minh"), _join(client, "Lan")
    client.post("/studies", json={"id": "ca1", "patient_name": "Nguyen Van A"}, headers=_as(minh))

    assert [p["name"] for p in client.get("/patients", headers=_as(minh)).json()] == ["Nguyen Van A"]
    assert client.get("/patients", headers=_as(lan)).json() == []
    # The operator's view, with no room, still sees everything.
    assert len(client.get("/patients").json()) == 1


def test_two_rooms_can_use_the_same_study_id_and_patient_name(env):
    """Without room scoping, the second "ca1" was a 409 and the second
    "Nguyen Van A" was silently the first clinician's patient."""
    client, Session, _ = env
    minh, lan = _join(client, "Minh"), _join(client, "Lan")
    for r in (minh, lan):
        resp = client.post(
            "/studies", json={"id": "ca1", "patient_name": "Nguyen Van A"}, headers=_as(r)
        )
        assert resp.status_code == 201, resp.text
    db = Session()
    assert db.query(Study).count() == 2
    assert db.query(Patient).count() == 2
    db.close()


def test_a_room_that_no_longer_exists_is_refused_not_widened(env):
    """Falling back to the operator's view would show one clinician everyone."""
    client, _, _ = env
    assert client.get("/patients", headers={"x-reader-id": "999"}).status_code == 401


def _make_sample(Session, data_dir: Path) -> None:
    study_dir = data_dir / "VAL-1"
    study_dir.mkdir()
    vol = study_dir / "vol.nii.gz"
    sitk.WriteImage(sitk.GetImageFromArray(np.zeros((3, 4, 4), dtype=np.int16)), str(vol))
    (study_dir / "mask.nii.gz").write_bytes(b"ai mask")
    db = Session()
    patient = Patient(name="RSNA 1")
    db.add(patient)
    db.flush()
    db.add(Study(id="VAL-1", patient_id=patient.id, volume_path=str(vol), display_path=str(vol)))
    db.add(Series(study_id="VAL-1", series_uid="s", volume_path=str(vol), orientation="sagittal"))
    db.add(Annotation(study_id="VAL-1", version=0, kind="ai",
                      payload_json={"grading": [{"level": "L4-L5", "condition": "canal_stenosis",
                                                 "severity": "Moderate"}]},
                      mask_path=str(study_dir / "mask.nii.gz")))
    # Someone already corrected the shared sample. That must not travel.
    db.add(Annotation(study_id="VAL-1", version=1, kind="corrected",
                      payload_json={"grading": [{"level": "L4-L5", "condition": "canal_stenosis",
                                                 "severity": "Severe"}]}))
    db.commit()
    db.close()


def test_a_sample_is_copied_into_the_room_as_the_model_graded_it(env):
    client, Session, data_dir = env
    _make_sample(Session, data_dir)
    minh = _join(client, "Minh")

    assert client.get("/samples", headers=_as(minh)).json() == [{"id": "VAL-1", "added": False}]
    resp = client.post(f"/readers/{minh['id']}/samples/VAL-1")
    assert resp.status_code == 201
    new_id = resp.json()["id"]

    db = Session()
    copy = db.get(Study, new_id)
    assert copy.reader_id == minh["id"]
    # Paths point into the copy's own directory, which really exists.
    assert Path(copy.volume_path).is_file()
    assert Path(copy.volume_path).parent.name == new_id
    anns = db.query(Annotation).filter_by(study_id=new_id).all()
    # Only the model's own output: the earlier "Severe" correction stayed behind.
    assert [a.kind for a in anns] == ["ai"]
    assert anns[0].payload_json["grading"][0]["severity"] == "Moderate"
    assert Path(anns[0].mask_path).parent.name == new_id
    db.close()

    assert client.get("/samples", headers=_as(minh)).json() == [{"id": "VAL-1", "added": True}]
    # Adding it twice does not make a second copy.
    assert client.post(f"/readers/{minh['id']}/samples/VAL-1").json()["created"] is False


def test_corrections_are_signed_with_the_room(env):
    """Agreement is reported per clinician, which needs to know who edited."""
    client, Session, data_dir = env
    _make_sample(Session, data_dir)
    minh = _join(client, "Minh")
    new_id = client.post(f"/readers/{minh['id']}/samples/VAL-1").json()["id"]

    edited = {
        "study_id": new_id,
        "model_version": "test",
        "segmentation": {"mask_uri": "", "labels": {}},
        "grading": [{"level": "L4-L5", "condition": "canal_stenosis",
                     "severity": "Severe", "score": 1.0}],
    }
    assert client.put(f"/studies/{new_id}/annotations", json=edited, headers=_as(minh)).status_code == 200
    db = Session()
    row = db.query(CorrectionLog).one()
    assert row.reader_id == minh["id"]
    assert (row.old, row.new) == ("Moderate", "Severe")
    db.close()


def test_a_room_has_a_personal_link_that_leads_back_into_it(env):
    """A clinician who forgets the name they typed can be sent their link."""
    client, _, _ = env
    minh = _join(client, "Minh")
    code = minh["code"]
    assert len(code) == 6 and not set(code) & set("0o1li")

    back = client.get(f"/readers/code/{code}").json()
    assert (back["id"], back["name"]) == (minh["id"], "Minh")
    # Case and stray spaces in a pasted link still land.
    assert client.get(f"/readers/code/{code.upper()}%20").json()["id"] == minh["id"]
    # Joining again by name returns the same link, not a fresh one.
    assert _join(client, "minh")["code"] == code
    assert _join(client, "Lan")["code"] != code


def test_an_unknown_link_is_refused(env):
    client, _, _ = env
    assert client.get("/readers/code/zzzzzz").status_code == 404
