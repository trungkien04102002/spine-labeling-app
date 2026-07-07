"""Tests for the /infer endpoint and LocalBackend composition."""

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
from app.inference.base import InferenceBackend, get_backend
from app.main import app
from app.models_db import Annotation, Patient, Study
from app.schemas import GradingItem, InferResult, SegmentationResult


class FakeBackend(InferenceBackend):
    """Returns a canned InferResult without running the real models."""

    def __init__(self, mask_path: str):
        self.mask_path = mask_path

    def infer(self, study_id, volume_path, grading_dir=None) -> InferResult:
        return InferResult(
            study_id=study_id,
            segmentation=SegmentationResult(
                mask_uri=self.mask_path, labels={41: "vertebrae_L1"}
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

    # A real (tiny) labelmap NIfTI the /infer endpoint can reorient into place.
    raw_mask = tmp_path / "raw_mask.nii.gz"
    mask_arr = np.zeros((8, 16, 24), dtype=np.uint16)
    mask_arr[2:5, 4:8, 6:10] = 41
    sitk.WriteImage(sitk.GetImageFromArray(mask_arr), str(raw_mask))

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: Settings(data_dir=str(tmp_path))
    app.dependency_overrides[get_backend] = lambda: FakeBackend(str(raw_mask))
    yield TestClient(app), TestingSession
    app.dependency_overrides.clear()


def test_infer_returns_contract_and_persists_v0(client):
    test_client, TestingSession = client

    resp = test_client.post("/studies/s1/infer")

    assert resp.status_code == 200
    body = resp.json()
    assert body["study_id"] == "s1"
    # mask_uri is rewritten to the API path the frontend loads from.
    assert body["segmentation"]["mask_uri"] == "/studies/s1/mask.nii.gz"
    assert len(body["grading"]) >= 1
    assert body["model_version"] == "fake-1.0"

    # A v0 "ai" annotation row was persisted, pointing at the reoriented mask.
    db = TestingSession()
    ann = db.query(Annotation).filter_by(study_id="s1").one()
    assert ann.version == 0
    assert ann.kind == "ai"
    assert ann.mask_path.endswith("s1/mask.nii.gz")
    assert Path(ann.mask_path).is_file()
    assert ann.payload_json["grading"][0]["level"] == "L4-L5"
    db.close()


def test_get_annotation_after_infer(client):
    test_client, _ = client
    assert test_client.get("/studies/s1/annotation").status_code == 404  # none yet

    test_client.post("/studies/s1/infer")

    resp = test_client.get("/studies/s1/annotation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["study_id"] == "s1"
    assert body["segmentation"]["mask_uri"] == "/studies/s1/mask.nii.gz"
    assert len(body["grading"]) >= 1


def test_infer_unknown_study_404(client):
    test_client, _ = client
    assert test_client.post("/studies/nope/infer").status_code == 404


def test_infer_without_volume_400(client):
    test_client, _ = client
    assert test_client.post("/studies/no_vol/infer").status_code == 400


def test_local_backend_runs_both_models(monkeypatch, tmp_path):
    """LocalBackend composes seg -> disc crops -> grading into one InferResult."""
    from app.inference import local

    monkeypatch.setattr(
        local, "run_segmentation", lambda vp: ("m.nii.gz", {2: "spinal_canal"})
    )
    # Stub the seg-driven crop step (its array math is covered by test_crops).
    monkeypatch.setattr(
        local,
        "_crops_from_mask",
        lambda vp, mp: {"L4-L5": {"crop": None, "bbox": [1, 2, 3, 4, 5]}},
    )
    monkeypatch.setattr(
        local,
        "grade_crops",
        lambda crops: [
            GradingItem(
                level=level,
                condition="canal_stenosis",
                severity="Severe",
                score=0.8,
                bbox=data["bbox"],
            )
            for level, data in crops.items()
        ],
    )

    result = local.LocalBackend().infer("s1", str(tmp_path / "v.mha"))
    assert result.study_id == "s1"
    assert result.segmentation.labels == {2: "spinal_canal"}
    assert result.grading[0].severity == "Severe"
    assert result.grading[0].bbox == [1, 2, 3, 4, 5]
