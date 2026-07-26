"""The path a correction takes: saved -> submitted -> a checkpoint someone can activate.

Covers the queue endpoints, the model-version registry, and the frozen
evaluation set. What is deliberately verified here is the *gating*: submitting
must not train anything, activating must be reversible, and a frozen set must
be detectably frozen.
"""

import csv
import datetime
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.feedback import freeze_holdout, model_registry
from app.main import app
from app.models_db import CorrectionLog, Patient, Study

_HEADS = ("spinal_canal", "left_foraminal", "right_foraminal")


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        test_client.db = TestingSession()  # type: ignore[attr-defined]
        yield test_client
    app.dependency_overrides.clear()


def _add_corrections(db, count: int, study_id: str = "study-1"):
    if db.get(Study, study_id) is None:
        patient = Patient(name="Test")
        db.add(patient)
        db.commit()
        db.refresh(patient)
        db.add(Study(id=study_id, patient_id=patient.id))
        db.commit()
    for i in range(count):
        db.add(
            CorrectionLog(
                study_id=study_id,
                field=f"l4_l5.{_HEADS[i % 3]}",
                old="Normal/Mild",
                new="Severe",
                at=datetime.datetime.utcnow(),
            )
        )
    db.commit()


# --- The queue -------------------------------------------------------------


def test_corrections_start_pending_and_are_counted(client):
    _add_corrections(client.db, 3)

    body = client.get("/corrections").json()

    assert body["pending"] == 3
    assert body["submitted"] == 0
    assert body["batches"] == 0
    assert len(body["recent"]) == 3


def test_submitting_moves_everything_pending_into_one_batch(client):
    _add_corrections(client.db, 4)

    result = client.post("/corrections/submit").json()
    after = client.get("/corrections").json()

    assert result["submitted"] == 4
    assert result["batch_id"].startswith("batch-")
    assert after["pending"] == 0
    assert after["submitted"] == 4
    assert after["batches"] == 1


def test_submitting_twice_is_harmless(client):
    """A doctor pressing the button again should get an answer, not an error."""
    _add_corrections(client.db, 2)
    client.post("/corrections/submit")

    second = client.post("/corrections/submit")

    assert second.status_code == 200
    assert second.json()["submitted"] == 0


def test_corrections_saved_after_a_submit_form_a_new_batch(client):
    _add_corrections(client.db, 2)
    first = client.post("/corrections/submit").json()

    _add_corrections(client.db, 3)
    pending_now = client.get("/corrections").json()["pending"]
    second = client.post("/corrections/submit").json()

    assert pending_now == 3, "later corrections must not join the sealed batch"
    assert second["batch_id"] != first["batch_id"]
    assert client.get("/corrections").json()["batches"] == 2


def test_submitting_does_not_change_the_served_model(client):
    """Queueing is not training -- the active checkpoint must be untouched."""
    _add_corrections(client.db, 3)
    before = client.get("/model/versions").json()

    client.post("/corrections/submit")

    assert client.get("/model/versions").json() == before


# --- Model versions --------------------------------------------------------


@pytest.fixture
def weights_dir(tmp_path, monkeypatch):
    directory = tmp_path / "weights"
    directory.mkdir()
    (directory / model_registry.BASELINE).write_bytes(b"baseline")
    monkeypatch.setattr(model_registry, "WEIGHTS_DIR", directory)
    monkeypatch.setattr(model_registry, "_invalidate_serving_model", lambda: None)
    return directory


def test_baseline_is_active_by_default(weights_dir):
    active = model_registry.active_checkpoint_name()

    assert active == model_registry.BASELINE


def test_activate_then_revert_round_trips(weights_dir):
    (weights_dir / "phase2_cbam_v2.pth").write_bytes(b"retrained")

    model_registry.activate("phase2_cbam_v2.pth")
    assert model_registry.active_checkpoint_name() == "phase2_cbam_v2.pth"

    model_registry.revert()
    assert model_registry.active_checkpoint_name() == model_registry.BASELINE


def test_activating_an_unknown_checkpoint_is_refused(weights_dir):
    with pytest.raises(model_registry.UnknownCheckpoint):
        model_registry.activate("does_not_exist.pth")


def test_checkpoint_name_cannot_escape_the_weights_directory(weights_dir):
    """The name arrives over HTTP; path traversal must not be reachable."""
    with pytest.raises(model_registry.UnknownCheckpoint):
        model_registry.activate("../../../etc/passwd.pth")


def test_a_dangling_pointer_falls_back_to_the_baseline(weights_dir):
    """Serving the known-good model beats refusing to serve."""
    (weights_dir / model_registry._POINTER).write_text("deleted_checkpoint.pth")

    assert model_registry.active_checkpoint_name() == model_registry.BASELINE


def test_listing_surfaces_sidecar_metrics(weights_dir):
    (weights_dir / "phase2_cbam_v2.pth").write_bytes(b"retrained")
    (weights_dir / "phase2_cbam_v2.pth.json").write_text(
        json.dumps({"before": {"macro_f1": 0.5}, "after": {"macro_f1": 0.6}})
    )

    listed = {c.name: c for c in model_registry.list_checkpoints()}

    assert listed["phase2_cbam_v2.pth"].metrics["after"]["macro_f1"] == 0.6
    assert listed[model_registry.BASELINE].metrics is None
    assert listed[model_registry.BASELINE].is_baseline


# --- The frozen evaluation set --------------------------------------------


def _write_source(root, n_rows: int, severe_every: int = 5):
    volumes = root / "volumes"
    volumes.mkdir(parents=True)
    rows = []
    for i in range(n_rows):
        filename = f"disc_{i}.npy"
        np.save(volumes / filename, np.zeros((9, 112, 224), dtype=np.float32))
        severity = "2" if i % severe_every == 0 else "0"
        rows.append({"filepath": filename, **{h: severity for h in _HEADS}})
    with open(root / "train_metadata.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["filepath", *_HEADS])
        writer.writeheader()
        writer.writerows(rows)
    return root


def test_freezing_writes_a_manifest_that_verifies(tmp_path):
    source = _write_source(tmp_path / "source", 60)
    out = tmp_path / "holdout"

    manifest = freeze_holdout.freeze_holdout(str(source), str(out), n=20, seed=42)
    ok, message = freeze_holdout.verify(str(out))

    assert manifest["n_rows"] == 20
    assert ok, message


def test_stratification_keeps_the_rare_class_in_the_holdout(tmp_path):
    """A uniform draw can miss Severe entirely, blinding the evaluation."""
    source = _write_source(tmp_path / "source", 100, severe_every=20)  # 5% Severe
    out = tmp_path / "holdout"

    freeze_holdout.freeze_holdout(str(source), str(out), n=10, seed=1)

    with open(out / "train_metadata.csv", newline="") as f:
        severities = [row["spinal_canal"] for row in csv.DictReader(f)]
    assert "2" in severities


def test_tampering_with_a_frozen_set_is_detected(tmp_path):
    source = _write_source(tmp_path / "source", 60)
    out = tmp_path / "holdout"
    freeze_holdout.freeze_holdout(str(source), str(out), n=20)

    with open(out / "train_metadata.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    rows[0]["spinal_canal"] = "1"  # quietly relabel one disc
    with open(out / "train_metadata.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["filepath", *_HEADS])
        writer.writeheader()
        writer.writerows(rows)

    ok, message = freeze_holdout.verify(str(out))

    assert not ok
    assert "CHANGED" in message


def test_refreezing_over_an_existing_set_is_refused(tmp_path):
    source = _write_source(tmp_path / "source", 60)
    out = tmp_path / "holdout"
    freeze_holdout.freeze_holdout(str(source), str(out), n=20)

    with pytest.raises(FileExistsError):
        freeze_holdout.freeze_holdout(str(source), str(out), n=20)


def test_holdout_cannot_swallow_the_whole_source(tmp_path):
    source = _write_source(tmp_path / "source", 30)

    with pytest.raises(ValueError, match="strict subset"):
        freeze_holdout.freeze_holdout(str(source), str(tmp_path / "holdout"), n=30)


def test_verify_reports_an_unfrozen_directory(tmp_path):
    empty = tmp_path / "nothing"
    empty.mkdir()

    ok, message = freeze_holdout.verify(str(empty))

    assert not ok
    assert "never frozen" in message
