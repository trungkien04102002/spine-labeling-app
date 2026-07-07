"""Tests for the /infer endpoint and LocalBackend composition."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import Base, get_db
from app.inference.base import InferenceBackend, get_backend
from app.main import app
from app.models_db import Annotation, Patient, Study
from app.schemas import GradingItem, InferResult, SegmentationResult


class FakeBackend(InferenceBackend):
    """Returns a canned InferResult without running the real models."""

    def infer(self, study_id, volume_path, grading_dir=None) -> InferResult:
        return InferResult(
            study_id=study_id,
            segmentation=SegmentationResult(
                mask_uri="/tmp/mask.nii.gz", labels={41: "vertebrae_L1"}
            ),
            grading=[
                GradingItem(
                    level="L4-L5",
                    condition="canal_stenosis",
                    severity="Moderate",
                    score=0.9,
                )
            ],
            model_version="fake-1.0",
        )


@pytest.fixture
def client(tmp_path):
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
    seed.add(
        Study(id="s1", patient_id=patient.id, volume_path=str(tmp_path / "v.mha"))
    )
    seed.add(Study(id="no_vol", patient_id=patient.id))  # no volume uploaded
    seed.commit()
    seed.close()

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: Settings(data_dir=str(tmp_path))
    app.dependency_overrides[get_backend] = lambda: FakeBackend()
    yield TestClient(app), TestingSession
    app.dependency_overrides.clear()


def test_infer_returns_contract_and_persists_v0(client):
    test_client, TestingSession = client

    resp = test_client.post("/studies/s1/infer")

    assert resp.status_code == 200
    body = resp.json()
    assert body["study_id"] == "s1"
    assert body["segmentation"]["mask_uri"]
    assert len(body["grading"]) >= 1
    assert body["model_version"] == "fake-1.0"

    # A v0 "ai" annotation row was persisted.
    db = TestingSession()
    ann = db.query(Annotation).filter_by(study_id="s1").one()
    assert ann.version == 0
    assert ann.kind == "ai"
    assert ann.mask_path == "/tmp/mask.nii.gz"
    assert ann.payload_json["grading"][0]["level"] == "L4-L5"
    db.close()


def test_infer_unknown_study_404(client):
    test_client, _ = client
    assert test_client.post("/studies/nope/infer").status_code == 404


def test_infer_without_volume_400(client):
    test_client, _ = client
    assert test_client.post("/studies/no_vol/infer").status_code == 400


def test_local_backend_runs_both_models(monkeypatch, tmp_path):
    """LocalBackend composes segmentation + grading into one InferResult."""
    from app.inference import local

    monkeypatch.setattr(
        local, "run_segmentation", lambda vp: ("/tmp/m.nii.gz", {2: "spinal_canal"})
    )
    monkeypatch.setattr(
        local,
        "run_grading",
        lambda gd: [
            GradingItem(
                level="L4-L5", condition="canal_stenosis", severity="Severe", score=0.8
            )
        ],
    )

    result = local.LocalBackend().infer(
        "s1", str(tmp_path / "v.mha"), grading_dir=str(tmp_path)
    )
    assert result.study_id == "s1"
    assert result.segmentation.labels == {2: "spinal_canal"}
    assert result.grading[0].severity == "Severe"
