"""Tests for multi-series studies (sagittal / axial in one upload).

A lumbar MRI study is several acquisitions -- typically sagittal T1, sagittal
T2 and axial T2 -- with different geometry, so they cannot be one volume. These
tests build synthetic DICOM series (no dependency on the gitignored samples) and
cover the regression that mattered: a zip holding two series used to lose one of
them silently, because every entry was flattened into one directory (colliding
filenames overwrote each other) and only the first series was ever read.
"""

from __future__ import annotations

import io
import zipfile
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
from app.inference.volume_io import extract_dicom_zip
from app.main import app
from app.models_db import Patient, Series, Study

# ImageOrientationPatient row/column cosines per acquisition plane.
_SAGITTAL = "0\\1\\0\\0\\0\\-1"
_AXIAL = "1\\0\\0\\0\\1\\0"


def _write_dicom_series(
    out_dir: Path,
    series_uid: str,
    orientation: str,
    description: str,
    num_slices: int = 4,
) -> None:
    """Write a tiny DICOM series with a fixed UID and acquisition plane.

    Slice files are deliberately named ``1.dcm..N.dcm`` in every series, so a
    zip of two series exercises the filename-collision path.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    writer = sitk.ImageFileWriter()
    writer.KeepOriginalImageUIDOn()
    rng = np.random.default_rng(0)
    for index in range(num_slices):
        slice_img = sitk.GetImageFromArray(
            (rng.random((8, 8)) * 255).astype(np.int16)
        )
        position = [0.0, 0.0, 0.0]
        # Step along the slice normal so SimpleITK can order/stack the slices.
        position[0 if orientation == _SAGITTAL else 2] = float(index) * 2.0
        for tag, value in [
            ("0008|0060", "MR"),
            ("0008|103e", description),
            ("0020|000d", "1.2.3.4.5"),  # StudyInstanceUID (shared)
            ("0020|000e", series_uid),  # SeriesInstanceUID (distinct)
            ("0020|0037", orientation),
            ("0020|0032", "\\".join(str(p) for p in position)),
            ("0020|0013", str(index + 1)),
            ("0018|0050", "2.0"),
            ("0028|0030", "1.0\\1.0"),
        ]:
            slice_img.SetMetaData(tag, value)
        writer.SetFileName(str(out_dir / f"{index + 1}.dcm"))
        writer.Execute(slice_img)


def _two_series_zip(tmp_path: Path) -> bytes:
    """A zip holding a sagittal and an axial series, with colliding filenames."""
    staging = tmp_path / "staging"
    _write_dicom_series(staging / "sag", "1.2.3.4.5.100", _SAGITTAL, "T2 SAG")
    _write_dicom_series(staging / "ax", "1.2.3.4.5.200", _AXIAL, "T2 AX")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path in sorted(staging.rglob("*.dcm")):
            zf.write(path, arcname=str(path.relative_to(staging)))
    return buf.getvalue()


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

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: Settings(data_dir=str(tmp_path))
    yield TestClient(app), TestingSession, tmp_path
    app.dependency_overrides.clear()


def test_extract_keeps_every_series(tmp_path):
    """The regression: both series survive, filename collisions and all."""
    zip_path = tmp_path / "study.zip"
    zip_path.write_bytes(_two_series_zip(tmp_path))

    found = extract_dicom_zip(str(zip_path), str(tmp_path / "out"))

    assert len(found) == 2, "a two-series zip must yield two series"
    assert sum(s.num_slices for s in found) == 8, "no slice may be dropped"
    # Each series lives in its own directory, so downstream readers (which
    # expect one series per directory) keep working unchanged.
    assert len({s.path for s in found}) == 2
    for info in found:
        assert len(list(Path(info.path).glob("*.dcm"))) == 4


def test_extract_detects_orientation_and_sorts_sagittal_first(tmp_path):
    zip_path = tmp_path / "study.zip"
    zip_path.write_bytes(_two_series_zip(tmp_path))

    found = extract_dicom_zip(str(zip_path), str(tmp_path / "out"))

    assert [s.orientation for s in found] == ["sagittal", "axial"]
    assert found[0].description == "T2 SAG"
    assert found[1].description == "T2 AX"


def test_upload_registers_both_series(client):
    test_client, TestingSession, tmp_path = client
    payload = _two_series_zip(tmp_path)

    resp = test_client.post(
        "/studies/s1/upload",
        files={"file": ("study.zip", payload, "application/zip")},
    )

    assert resp.status_code == 200
    assert resp.json()["series_count"] == 2

    db = TestingSession()
    rows = db.query(Series).filter_by(study_id="s1").order_by(Series.id).all()
    assert [r.orientation for r in rows] == ["sagittal", "axial"]
    # The sagittal series is active by default: it is what the models read.
    study = db.get(Study, "s1")
    assert study.volume_path == rows[0].volume_path
    db.close()


def test_list_series_marks_active_and_unanalyzed(client):
    test_client, _, tmp_path = client
    test_client.post(
        "/studies/s1/upload",
        files={"file": ("study.zip", _two_series_zip(tmp_path), "application/zip")},
    )

    body = test_client.get("/studies/s1/series").json()

    assert [s["orientation"] for s in body] == ["sagittal", "axial"]
    assert [s["is_active"] for s in body] == [True, False]
    # Nothing has been analyzed yet, so the UI must not imply otherwise.
    assert [s["analyzed_by_ai"] for s in body] == [False, False]
    assert all(s["num_slices"] == 4 for s in body)


def test_switch_active_series(client):
    test_client, TestingSession, tmp_path = client
    test_client.post(
        "/studies/s1/upload",
        files={"file": ("study.zip", _two_series_zip(tmp_path), "application/zip")},
    )
    axial_id = test_client.get("/studies/s1/series").json()[1]["id"]

    resp = test_client.put(
        "/studies/s1/active_series", json={"series_id": axial_id}
    )

    assert resp.status_code == 200
    assert [s["is_active"] for s in resp.json()] == [False, True]

    db = TestingSession()
    study = db.get(Study, "s1")
    axial = db.get(Series, axial_id)
    assert study.volume_path == axial.volume_path
    # Switching builds the viewer volume for that series on demand.
    assert study.display_path == axial.display_path
    assert Path(axial.display_path).is_file()
    db.close()


def test_switch_to_foreign_series_404(client):
    test_client, TestingSession, tmp_path = client
    test_client.post(
        "/studies/s1/upload",
        files={"file": ("study.zip", _two_series_zip(tmp_path), "application/zip")},
    )
    db = TestingSession()
    patient = db.query(Patient).first()
    db.add(Study(id="s2", patient_id=patient.id))
    db.commit()
    other = Series(
        study_id="s2", series_uid="x", orientation="axial", volume_path="/tmp/x"
    )
    db.add(other)
    db.commit()
    other_id = other.id
    db.close()

    resp = test_client.put(
        "/studies/s1/active_series", json={"series_id": other_id}
    )
    assert resp.status_code == 404


def test_reupload_replaces_series_rows(client):
    test_client, TestingSession, tmp_path = client
    payload = _two_series_zip(tmp_path)
    test_client.post(
        "/studies/s1/upload",
        files={"file": ("study.zip", payload, "application/zip")},
    )
    test_client.post(
        "/studies/s1/upload",
        files={"file": ("study.zip", payload, "application/zip")},
    )

    db = TestingSession()
    rows = db.query(Series).filter_by(study_id="s1").all()
    assert len(rows) == 2, "re-upload must replace, not accumulate, series rows"
    db.close()


def test_single_file_upload_still_has_one_series(client, tmp_path):
    """MHA/NIfTI have no series concept: the file itself is the one series."""
    test_client, TestingSession, data_dir = client
    array = (np.random.default_rng(0).random((6, 12, 12)) * 255).astype(np.float32)
    src = tmp_path / "vol.nii.gz"
    sitk.WriteImage(sitk.GetImageFromArray(array), str(src))

    resp = test_client.post(
        "/studies/s1/upload",
        files={"file": ("vol.nii.gz", src.read_bytes(), "application/octet-stream")},
    )

    assert resp.status_code == 200
    assert resp.json()["series_count"] == 1
    body = test_client.get("/studies/s1/series").json()
    assert len(body) == 1
    assert body[0]["is_active"] is True
