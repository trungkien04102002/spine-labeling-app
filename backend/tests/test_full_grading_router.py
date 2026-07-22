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

    def fake_build_full_grading(study_id, volume_path):
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
        return result, b"\x89PNG\r\n\x1a\nfake-png-bytes"

    monkeypatch.setattr(
        full_grading_router, "build_full_grading", fake_build_full_grading
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

    assert (tmp_path / "s1" / "grade_full.json").is_file()
    assert (tmp_path / "s1" / "spinenet_slice.png").is_file()


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
