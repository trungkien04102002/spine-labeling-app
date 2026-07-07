"""Tests for the study upload endpoint."""

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
from app.models_db import Patient, Study


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
    seed.add(Study(id="s1", patient_id=patient.id))
    seed.commit()
    seed.close()

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    def override_settings():
        return Settings(data_dir=str(tmp_path))

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = override_settings
    yield TestClient(app), TestingSession, tmp_path
    app.dependency_overrides.clear()


def _nifti_bytes(tmp_path) -> bytes:
    array = (np.random.default_rng(0).random((6, 12, 12)) * 255).astype(np.float32)
    img = sitk.GetImageFromArray(array)
    img.SetSpacing((1.0, 1.0, 2.0))
    src = tmp_path / "upload_src.nii.gz"
    sitk.WriteImage(img, str(src))
    return src.read_bytes()


def test_upload_stores_and_converts(client):
    test_client, TestingSession, data_dir = client
    payload = _nifti_bytes(data_dir)

    resp = test_client.post(
        "/studies/s1/upload",
        files={"file": ("vol.nii.gz", payload, "application/octet-stream")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["study_id"] == "s1"
    assert body["volume_path"]
    assert body["display_path"].endswith(".nii.gz")

    # Files exist on disk.
    assert Path(body["volume_path"]).exists()
    assert Path(body["display_path"]).exists()

    # DB row updated.
    db = TestingSession()
    study = db.get(Study, "s1")
    assert study.volume_path == body["volume_path"]
    assert study.display_path == body["display_path"]
    db.close()


def test_display_served_after_upload(client):
    test_client, _, data_dir = client
    payload = _nifti_bytes(data_dir)
    test_client.post(
        "/studies/s1/upload",
        files={"file": ("vol.nii.gz", payload, "application/octet-stream")},
    )

    resp = test_client.get("/studies/s1/display.nii.gz")
    assert resp.status_code == 200
    assert len(resp.content) > 0


def test_display_missing_404(client):
    test_client, _, _ = client
    # s1 has no upload yet in this test.
    assert test_client.get("/studies/s1/display.nii.gz").status_code == 404


def test_study_detail_reports_metadata(client):
    test_client, _, data_dir = client
    payload = _nifti_bytes(data_dir)
    test_client.post(
        "/studies/s1/upload",
        files={"file": ("vol.nii.gz", payload, "application/octet-stream")},
    )

    resp = test_client.get("/studies/s1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "s1"
    assert body["patient_name"] == "Demo"
    assert body["has_volume"] is True
    assert body["has_mask"] is False
    assert len(body["dimensions"]) == 3
    assert body["num_slices"] == body["dimensions"][2]
    # A NIfTI/MHA source carries no acquisition tags.
    assert body["dicom_tags"] == {}


def test_study_detail_unknown_404(client):
    test_client, _, _ = client
    assert test_client.get("/studies/nope").status_code == 404


def test_upload_unknown_study_404(client):
    test_client, _, data_dir = client
    payload = _nifti_bytes(data_dir)

    resp = test_client.post(
        "/studies/nope/upload",
        files={"file": ("vol.nii.gz", payload, "application/octet-stream")},
    )
    assert resp.status_code == 404
