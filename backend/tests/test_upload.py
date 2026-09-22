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


def test_upload_rejects_unsupported_type(client):
    test_client, _, _ = client
    resp = test_client.post(
        "/studies/s1/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400
    assert "Unsupported file type" in resp.json()["detail"]


def test_upload_rejects_non_dicom_zip(client):
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "not a dicom")

    test_client, _, _ = client
    resp = test_client.post(
        "/studies/s1/upload",
        files={"file": ("series.zip", buf.getvalue(), "application/zip")},
    )
    assert resp.status_code == 400
    assert "DICOM" in resp.json()["detail"]


def test_reupload_clears_the_previous_image_s_results(client, tmp_path):
    """A second upload must not leave the first image's mask and grades behind.

    Replacing the volume in a study is how someone fixes sending the wrong
    file. If the mask, the grading JSON and the annotation rows survive, the
    viewer draws one patient's segmentation over another's scan and shows
    grades that were never computed from it -- wrong, and plausible enough that
    nobody questions it.
    """
    test_client, TestingSession, data_dir = client

    volume = tmp_path / "first.nii.gz"
    image = sitk.GetImageFromArray(np.zeros((4, 8, 8), dtype=np.int16))
    sitk.WriteImage(image, str(volume))
    test_client.post(
        "/studies/s1/upload",
        files={"file": ("first.nii.gz", volume.read_bytes(), "application/gzip")},
    )

    # Stand in for what a grading run leaves behind.
    study_dir = Path(data_dir) / "s1"
    (study_dir / "mask.nii.gz").write_bytes(b"old mask")
    (study_dir / "grade_full.json").write_text('{"grading": []}')
    session = TestingSession()
    session.add(
        Annotation(
            study_id="s1",
            version=1,
            kind="ai",
            payload_json={"from": "the first image"},
            mask_path=str(study_dir / "mask.nii.gz"),
        )
    )
    session.commit()
    session.close()

    second = tmp_path / "second.nii.gz"
    sitk.WriteImage(
        sitk.GetImageFromArray(np.ones((4, 8, 8), dtype=np.int16)), str(second)
    )
    resp = test_client.post(
        "/studies/s1/upload",
        files={"file": ("second.nii.gz", second.read_bytes(), "application/gzip")},
    )
    assert resp.status_code == 200

    assert not (study_dir / "mask.nii.gz").exists()
    assert not (study_dir / "grade_full.json").exists()
    assert not (study_dir / "first.nii.gz").exists()
    session = TestingSession()
    assert session.query(Annotation).filter_by(study_id="s1").count() == 0
    session.close()


def test_rejection_names_what_the_archive_held(client):
    """A refusal has to be answerable without asking for the file.

    When a doctor's study will not open, the only person who can see the
    archive is the doctor. A message that just says "no DICOM series" starts a
    round trip; one that reports the file count, the extensions and why the
    first files did not parse usually ends the question immediately.
    """
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("scan.jpg", "not a dicom at all")
        zf.writestr("notes.txt", "nor this")

    test_client, _, _ = client
    resp = test_client.post(
        "/studies/s1/upload",
        files={"file": ("study.zip", buf.getvalue(), "application/zip")},
    )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "2 file(s)" in detail
    assert ".jpg" in detail and ".txt" in detail
    # and it says why a specific file failed, not merely that one did
    assert "scan.jpg" in detail


_SAMPLE_DICOM_ZIP = Path(
    "/Users/kienha/spine-labeling-app/sample_volumes/sample_dicom.zip"
)


@pytest.mark.skipif(
    not _SAMPLE_DICOM_ZIP.is_file(),
    reason="sample DICOM zip not present (sample_volumes is gitignored)",
)
def test_upload_dicom_zip(client):
    test_client, TestingSession, _ = client
    resp = test_client.post(
        "/studies/s1/upload",
        files={
            "file": (
                "series.zip",
                _SAMPLE_DICOM_ZIP.read_bytes(),
                "application/zip",
            )
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # A DICOM zip becomes a directory of slices; the display volume is NIfTI.
    assert Path(body["volume_path"]).is_dir()
    assert body["display_path"].endswith(".nii.gz")
    assert Path(body["display_path"]).exists()
