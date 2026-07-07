"""Tests for the study export endpoint."""

import io
import zipfile

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
from app.models_db import Annotation, Patient, Study


def _write_nifti(path, fill=None):
    arr = np.zeros((6, 40, 30), dtype=np.int16) if fill is None else fill
    sitk.WriteImage(sitk.GetImageFromArray(arr), str(path))


@pytest.fixture
def client(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    display = tmp_path / "disp.nii.gz"
    _write_nifti(display, (np.random.default_rng(0).random((6, 40, 30)) * 500).astype(np.int16))
    study_dir = tmp_path / "s1"
    study_dir.mkdir()
    mask = study_dir / "mask.nii.gz"
    mask_arr = np.zeros((6, 40, 30), dtype=np.uint16)
    mask_arr[2:4, 10:20, 10:20] = 95
    _write_nifti(mask, mask_arr)

    seed = TestingSession()
    patient = Patient(name="Demo")
    seed.add(patient)
    seed.commit()
    seed.refresh(patient)
    seed.add(Study(id="s1", patient_id=patient.id, display_path=str(display)))
    seed.add(
        Annotation(
            study_id="s1",
            version=0,
            kind="ai",
            payload_json={
                "study_id": "s1",
                "segmentation": {"mask_uri": "/studies/s1/mask.nii.gz", "labels": {}},
                "grading": [
                    {
                        "level": "L4-L5",
                        "condition": "canal_stenosis",
                        "severity": "Severe",
                        "score": 0.8,
                        "bbox": [3, 1, 2, 3, 4],
                        "heatmap_uri": None,
                    }
                ],
                "model_version": "fake-1.0",
            },
            mask_path=str(mask),
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
    app.dependency_overrides[get_settings] = lambda: Settings(data_dir=str(tmp_path))
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_export_returns_zip_with_expected_members(client):
    resp = client.get("/studies/s1/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = set(zf.namelist())
    assert {"grades.csv", "grades.json", "original.nii.gz", "mask.nii.gz"} <= names
    assert "labeled_midsag.png" in names

    csv_text = zf.read("grades.csv").decode()
    assert "level,condition,severity,score,bbox" in csv_text
    assert "L4-L5" in csv_text and "Severe" in csv_text


def test_export_unknown_study_404(client):
    assert client.get("/studies/nope/export").status_code == 404


def test_export_without_annotation_404(client):
    # Wipe the annotation via a fresh study with none.
    resp = client.get("/studies/no_such/export")
    assert resp.status_code == 404
