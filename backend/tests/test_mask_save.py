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
from app.models_db import Annotation, Patient, Study


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

    # Tests that need an annotation version line add one themselves.

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


# --- A mask edit must be undoable ------------------------------------------
#
# Grade corrections have always been versioned: every edit is a new
# `annotations` row and the previous one is still there. A mask edit used to
# write straight over `mask.nii.gz`, so a stray brush stroke saved by accident
# destroyed the segmentation it replaced -- the traceability this tool claims
# held for only half of what a doctor can change.


def _seed_annotation(client_fixture, mask_path, version=0, kind="ai"):
    """Give the study the annotation row inference would have left behind."""
    test_client, _ = client_fixture
    db = next(test_client.app.dependency_overrides[get_db]())
    db.add(
        Annotation(
            study_id="s1",
            version=version,
            kind=kind,
            payload_json={"grading": []},
            mask_path=str(mask_path),
        )
    )
    db.commit()
    db.close()


def _annotations(client_fixture):
    test_client, _ = client_fixture
    db = next(test_client.app.dependency_overrides[get_db]())
    rows = (
        db.query(Annotation)
        .filter_by(study_id="s1")
        .order_by(Annotation.version, Annotation.id)
        .all()
    )
    out = [(r.version, r.kind, r.mask_path) for r in rows]
    db.close()
    return out


def _put(test_client, value):
    voxels = np.zeros((3, 4, 5), dtype=np.uint8)
    voxels[1, 2, 3] = value
    return test_client.put("/studies/s1/mask", content=voxels.tobytes())


def test_first_save_has_nothing_to_keep(client):
    test_client, _ = client

    body = _put(test_client, 95).json()

    assert body["previous_mask"] is None


def test_overwriting_a_mask_keeps_the_previous_one(client):
    test_client, tmp_path = client
    _put(test_client, 95)  # the "real" mask
    live = tmp_path / "s1" / "mask.nii.gz"
    _seed_annotation(client, live)

    body = _put(test_client, 42).json()  # the stray stroke

    archived = tmp_path / "s1" / "mask_versions" / body["previous_mask"]
    assert archived.is_file(), "the overwritten mask must still exist"
    old = sitk.GetArrayFromImage(sitk.ReadImage(str(archived)))
    assert old[1, 2, 3] == 95, "the archive holds what was there before"
    new = sitk.GetArrayFromImage(sitk.ReadImage(str(live)))
    assert new[1, 2, 3] == 42, "and the live mask is the new edit"


def test_the_serving_path_is_untouched(client):
    """The viewer and the export read `mask.nii.gz`; that must not move."""
    test_client, tmp_path = client
    _put(test_client, 95)
    _seed_annotation(client, tmp_path / "s1" / "mask.nii.gz")

    _put(test_client, 42)

    served = test_client.get("/studies/s1/mask.nii.gz")
    assert served.status_code == 200
    assert (tmp_path / "s1" / "mask.nii.gz").is_file()


def test_each_version_points_at_the_file_holding_its_own_mask(client):
    """`annotations.mask_path` is per version -- so it has to stay true."""
    test_client, tmp_path = client
    _put(test_client, 95)
    live = (tmp_path / "s1" / "mask.nii.gz").resolve()
    _seed_annotation(client, live)

    body = _put(test_client, 42).json()

    rows = _annotations(client)
    assert len(rows) == 2, "a mask edit is a new version, like a grade edit"
    (v0, kind0, path0), (v1, kind1, path1) = rows
    assert (v0, kind0) == (0, "ai")
    assert path0.endswith(body["previous_mask"]), "v0 now names its archived mask"
    assert (v1, kind1, body["version"]) == (1, "mask", 1)
    assert path1 == str(live), "the newest version still names the live mask"


def test_three_saves_keep_all_three_earlier_masks(client):
    test_client, tmp_path = client
    _put(test_client, 95)
    _seed_annotation(client, tmp_path / "s1" / "mask.nii.gz")
    _put(test_client, 42)
    _put(test_client, 7)

    kept = sorted((tmp_path / "s1" / "mask_versions").glob("mask_v*.nii.gz"))
    assert len(kept) == 2, "every superseded mask is kept, none pruned"
    values = [
        sitk.GetArrayFromImage(sitk.ReadImage(str(p)))[1, 2, 3] for p in kept
    ]
    assert values == [95, 42], "in the order they were replaced"
