"""Tests for persisting a doctor-edited labelmap (PUT /studies/{id}/mask)."""

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

    display = tmp_path / "disp.nii.gz"
    # size (x=5, y=4, z=3) -> array (z, y, x)
    sitk.WriteImage(sitk.GetImageFromArray(np.zeros((3, 4, 5), dtype=np.int16)), str(display))

    seed = TestingSession()
    patient = Patient(name="Demo")
    seed.add(patient)
    seed.commit()
    seed.refresh(patient)
    seed.add(Study(id="s1", patient_id=patient.id, display_path=str(display)))
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
    yield TestClient(app), tmp_path
    app.dependency_overrides.clear()


def test_put_mask_writes_aligned_nifti(client):
    test_client, tmp_path = client
    voxels = np.zeros((3, 4, 5), dtype=np.uint8)
    voxels[1, 2, 3] = 95  # one labeled voxel
    resp = test_client.put(
        "/studies/s1/mask", content=voxels.tobytes()
    )
    assert resp.status_code == 200
    assert resp.json()["shape"] == [3, 4, 5]

    written = sitk.GetArrayFromImage(sitk.ReadImage(str(tmp_path / "s1" / "mask.nii.gz")))
    assert written.shape == (3, 4, 5)
    assert written[1, 2, 3] == 95
    assert written.sum() == 95


def test_put_mask_wrong_size_400(client):
    test_client, _ = client
    resp = test_client.put("/studies/s1/mask", content=b"\x00\x01\x02")
    assert resp.status_code == 400


def test_put_mask_unknown_study_404(client):
    test_client, _ = client
    assert test_client.put("/studies/nope/mask", content=b"").status_code == 404
