"""Tests for the /studies/{id}/grade_full endpoints.

`build_full_grading` (which runs the real, heavy SpineNet + CBAM pipelines) is
monkeypatched to a fake that returns a canned result -- these tests only cover
endpoint wiring, persistence, and the CSV/JSON/PNG download contracts.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import Base, get_db
from app.main import app
from app.models_db import Patient, Study
from app.schemas import FullGradingResult, GradingItem


@pytest.fixture
def client(tmp_path, monkeypatch):
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
    seed.add(Study(id="no_vol", patient_id=patient.id))
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

    from app.routers import full_grading as full_grading_router

    def fake_build_full_grading(study_id, volume_path, progress=None):
        if progress is not None:
            progress("Fake stage", 50)
        result = FullGradingResult(
            study_id=study_id,
            grading=[
                GradingItem(
                    level="L4-L5", condition="canal_stenosis", severity="Moderate", score=0.9
                ),
                GradingItem(
                    level="L4-L5", condition="pfirrmann", severity="Grade 3", score=0.8
                ),
            ],
            slice_image_uri=f"/studies/{study_id}/grade_full/slice.png",
            model_version="spinenet-upstream + phase2-cbam",
        )
        # (result, png, raw_mask_path, labels) -- the router reorients the mask.
        return (
            result,
            b"\x89PNG\r\n\x1a\nfake-png-bytes",
            "raw_mask.nii.gz",
            {2: "spinal_canal"},
        )

    monkeypatch.setattr(
        full_grading_router, "build_full_grading", fake_build_full_grading
    )
    # The background job opens its own session (the request's is closed once the
    # response goes out), so dependency_overrides does not reach it -- without
    # this it would talk to the real configured database.
    monkeypatch.setattr(full_grading_router, "SessionLocal", TestingSession)
    # to_web_mask reorients a real NIfTI into the study dir; stub it (no file I/O)
    # so these wiring tests don't need a real labelmap on disk.
    monkeypatch.setattr(
        full_grading_router,
        "to_web_mask",
        lambda mask_path, out_dir: str(Path(out_dir) / "mask.nii.gz"),
    )

    yield TestClient(app), tmp_path
    app.dependency_overrides.clear()


def test_grade_full_returns_merged_table_and_persists_files(client):
    test_client, tmp_path = client

    resp = test_client.post("/studies/s1/grade_full")

    assert resp.status_code == 200
    body = resp.json()
    assert body["study_id"] == "s1"
    assert len(body["grading"]) == 2
    assert body["slice_image_uri"] == "/studies/s1/grade_full/slice.png"
    # The run now also persists the segmentation mask + a v0 AI annotation so the
    # editable panel / correction pipeline can load the 11-label grading.
    assert body["segmentation"]["mask_uri"] == "/studies/s1/mask.nii.gz"

    assert (tmp_path / "s1" / "grade_full.json").is_file()
    assert (tmp_path / "s1" / "spinenet_slice.png").is_file()


def test_grade_full_saves_editable_annotation(client):
    test_client, _ = client
    test_client.post("/studies/s1/grade_full")

    # getAnnotation must now return the full 11-label grading (editable panel).
    resp = test_client.get("/studies/s1/annotation")
    assert resp.status_code == 200
    body = resp.json()
    assert {g["condition"] for g in body["grading"]} == {"canal_stenosis", "pfirrmann"}
    assert body["segmentation"]["mask_uri"] == "/studies/s1/mask.nii.gz"


def test_grade_full_unknown_study_404(client):
    test_client, _ = client
    assert test_client.post("/studies/nope/grade_full").status_code == 404


def test_grade_full_without_volume_400(client):
    test_client, _ = client
    assert test_client.post("/studies/no_vol/grade_full").status_code == 400


def test_get_grade_full_before_post_404(client):
    test_client, _ = client
    assert test_client.get("/studies/s1/grade_full").status_code == 404


def test_get_grade_full_after_post_returns_cached_result(client):
    test_client, _ = client
    test_client.post("/studies/s1/grade_full")

    resp = test_client.get("/studies/s1/grade_full")
    assert resp.status_code == 200
    assert resp.json()["study_id"] == "s1"


def test_grade_full_csv_download(client):
    test_client, _ = client
    test_client.post("/studies/s1/grade_full")

    resp = test_client.get("/studies/s1/grade_full.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.strip().splitlines()
    assert lines[0] == "level,condition,severity,score"
    assert any("canal_stenosis" in line for line in lines)


def test_grade_full_json_download(client):
    test_client, _ = client
    test_client.post("/studies/s1/grade_full")

    resp = test_client.get("/studies/s1/grade_full.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["study_id"] == "s1"


def test_grade_full_slice_png(client):
    test_client, _ = client
    test_client.post("/studies/s1/grade_full")

    resp = test_client.get("/studies/s1/grade_full/slice.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG")


def test_grade_full_downloads_404_before_post(client):
    test_client, _ = client
    assert test_client.get("/studies/s1/grade_full.csv").status_code == 404
    assert test_client.get("/studies/s1/grade_full.json").status_code == 404
    assert test_client.get("/studies/s1/grade_full/slice.png").status_code == 404


# --- The background path -------------------------------------------------


def _poll_until_done(test_client, job_id, timeout=5.0):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        body = test_client.get(f"/jobs/{job_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


def test_start_returns_a_job_immediately_and_grades_in_the_background(client):
    test_client, _ = client

    start = test_client.post("/studies/s1/grade_full/start")

    assert start.status_code == 202, "the work has not happened yet"
    job = start.json()
    assert job["status"] == "running"

    finished = _poll_until_done(test_client, job["id"])
    assert finished["status"] == "done"
    assert finished["percent"] == 100

    # The result is persisted, so a client that missed the end can still read it.
    cached = test_client.get("/studies/s1/grade_full")
    assert cached.status_code == 200
    assert cached.json()["study_id"] == "s1"


def test_starting_twice_returns_the_run_already_in_flight(client, monkeypatch):
    """Two concurrent runs would race over the same result files."""
    import threading

    from app.routers import full_grading as full_grading_router

    test_client, _ = client
    release = threading.Event()
    started = threading.Event()
    real_fake = full_grading_router.build_full_grading

    def slow(study_id, volume_path, progress=None):
        # Hold the first run open so the second genuinely overlaps it; with an
        # instant fake the first would finish and the second would be free to
        # start, which is not the situation this test is about.
        started.set()
        release.wait(timeout=5)
        return real_fake(study_id, volume_path, progress)

    monkeypatch.setattr(full_grading_router, "build_full_grading", slow)

    first = test_client.post("/studies/s1/grade_full/start").json()
    assert started.wait(timeout=5)
    second = test_client.post("/studies/s1/grade_full/start").json()

    assert second["id"] == first["id"], (
        "a second start must join the running job, not launch a rival one"
    )

    release.set()
    assert _poll_until_done(test_client, first["id"])["status"] == "done"


def test_start_rejects_an_unknown_study_up_front(client):
    """Bad requests must fail now, not become a job that fails later."""
    test_client, _ = client

    response = test_client.post("/studies/nope/grade_full/start")

    assert response.status_code == 404


def test_start_rejects_a_study_with_no_volume_up_front(client):
    test_client, _ = client

    response = test_client.post("/studies/no_vol/grade_full/start")

    assert response.status_code == 400


def test_unknown_job_id_is_404(client):
    test_client, _ = client
    assert test_client.get("/jobs/deadbeef").status_code == 404


def test_a_failing_run_surfaces_as_an_errored_job(client, monkeypatch):
    """A crash must be visible, not an eternal spinner."""
    from app.routers import full_grading as full_grading_router

    def boom(study_id, volume_path, progress=None):
        raise RuntimeError("TotalSpineSeg binary not found")

    monkeypatch.setattr(full_grading_router, "build_full_grading", boom)

    test_client, _ = client
    job = test_client.post("/studies/s1/grade_full/start").json()
    finished = _poll_until_done(test_client, job["id"])

    assert finished["status"] == "error"
    assert "TotalSpineSeg binary not found" in finished["error"]
