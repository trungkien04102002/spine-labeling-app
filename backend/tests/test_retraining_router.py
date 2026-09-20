"""Tests for running one re-training batch from the operator page.

The heavy parts (`build_finetune_dataset`, `retrain_head`) are stubbed: what is
under test here is the wiring and, above all, the promises the screen makes.
Three of them are the reason this endpoint is allowed to exist at all:

* two runs can never overlap,
* a missing replay set is refused in words, not silently worked around,
* and a finished run -- even a successful one -- changes nothing about which
  checkpoint grades the next patient.
"""

from __future__ import annotations

import csv
import datetime
import threading
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings, get_settings
from app.db import Base, get_db
from app.feedback import freeze_holdout, model_registry
from app.feedback.build_dataset import BuildResult
from app.feedback.retrain_head import RetrainResult
from app.main import app
from app.models_db import CorrectionLog, Patient, RetrainRun, Study, mark_interrupted_runs
from app.routers import retraining

_HEADS = ("spinal_canal", "left_foraminal", "right_foraminal")
_BATCH = "batch-20260920-101112-abc123"


def _wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _write_dataset_dir(root, n_rows: int = 30):
    """A `build_finetune_dataset`-shaped directory (used as source/replay)."""
    volumes = root / "volumes"
    volumes.mkdir(parents=True)
    rows = []
    for i in range(n_rows):
        filename = f"disc_{i}.npy"
        np.save(volumes / filename, np.zeros((9, 112, 224), dtype=np.float32))
        rows.append({"filepath": filename, **{h: "2" if i % 5 == 0 else "0" for h in _HEADS}})
    with open(root / "train_metadata.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["filepath", *_HEADS])
        writer.writeheader()
        writer.writerows(rows)
    return root


@pytest.fixture
def weights_dir(tmp_path, monkeypatch):
    directory = tmp_path / "weights"
    directory.mkdir()
    (directory / model_registry.BASELINE).write_bytes(b"baseline")
    monkeypatch.setattr(model_registry, "WEIGHTS_DIR", directory)
    monkeypatch.setattr(model_registry, "_invalidate_serving_model", lambda: None)
    return directory


@pytest.fixture
def env(tmp_path, monkeypatch, weights_dir):
    """A client whose backend has a frozen held-out set and a replay set."""
    # A file-backed SQLite, not an in-memory one: the background job runs on
    # its own thread with its own session, and a shared single connection
    # (StaticPool) would have the two threads interleaving transactions on it.
    engine = create_engine(
        f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    seed = TestingSession()
    patient = Patient(name="Demo")
    seed.add(patient)
    seed.commit()
    seed.refresh(patient)
    seed.add(Study(id="study-1", patient_id=patient.id))
    seed.add(
        CorrectionLog(
            study_id="study-1",
            field="L4-L5/canal_stenosis",
            old="Normal/Mild",
            new="Severe",
            at=datetime.datetime.utcnow(),
            submitted_at=datetime.datetime.utcnow(),
            batch_id=_BATCH,
        )
    )
    seed.commit()
    seed.close()

    # The frozen held-out set the before/after numbers are measured on.
    source = _write_dataset_dir(tmp_path / "source", 60)
    freeze_holdout.freeze_holdout(str(source), str(tmp_path / "holdout_frozen"), n=20)
    replay = _write_dataset_dir(tmp_path / "replay", 25)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    # A background job opens its own session; dependency_overrides does not
    # reach it, so point the module's factory at the test database too.
    monkeypatch.setattr(retraining, "SessionLocal", TestingSession)

    def use_settings(**extra):
        app.dependency_overrides[get_settings] = lambda: Settings(
            data_dir=str(tmp_path), **extra
        )

    use_settings(retrain_replay_dir=str(replay))

    with TestClient(app) as client:
        client.db = TestingSession()  # type: ignore[attr-defined]
        client.use_settings = use_settings  # type: ignore[attr-defined]
        client.replay_dir = str(replay)  # type: ignore[attr-defined]
        client.weights_dir = weights_dir  # type: ignore[attr-defined]
        yield client
    app.dependency_overrides.clear()


def _stub_build(monkeypatch, num_rows: int = 3, skipped=None):
    """Stand in for the rebuild; returns a dict recording how it was called."""
    seen: dict = {}

    def fake_build(db, out_dir, crop_fn=None, batch_id=None, submitted_only=True):
        seen["out_dir"] = out_dir
        seen["batch_id"] = batch_id
        seen["submitted_only"] = submitted_only
        return BuildResult(
            out_dir=out_dir,
            metadata_csv=f"{out_dir}/train_metadata.csv",
            num_rows=num_rows,
            num_corrections_used=1,
            skipped=list(skipped or []),
        )

    monkeypatch.setattr(
        retraining.build_dataset, "build_finetune_dataset", fake_build
    )
    return seen


def _stub_retrain(monkeypatch, improved: bool, gate=None, boom: Exception | None = None):
    """Stand in for the real fine-tune; optionally block on `gate` or raise."""
    calls = {}

    def fake_retrain(**kwargs):
        calls.update(kwargs)
        if gate is not None:
            gate.wait(timeout=10)
        if boom is not None:
            raise boom
        before = {"macro_f1": 0.40, "severe_f1": 0.0, "mean_acc": 0.7}
        after = {"macro_f1": 0.51 if improved else 0.38, "severe_f1": 0.2, "mean_acc": 0.7}
        out = kwargs["out_checkpoint"]
        if improved:
            # The real function writes the candidate itself; mimic just that.
            open(out, "wb").write(b"candidate")
        return RetrainResult(
            before=before,
            after=after,
            improved=improved,
            checkpoint_path=out if improved else None,
        )

    monkeypatch.setattr(retraining.retrain_head, "retrain_head", fake_retrain)
    return calls


def _finished(client, run_id: int) -> RetrainRun:
    assert _wait_for(
        lambda: client.db.get(RetrainRun, run_id) is not None
        and _refresh(client, run_id).status != "running",
        timeout=15,
    ), "the run never finished"
    return _refresh(client, run_id)


def _job_status(client, job_id: str) -> str:
    """The job's own verdict, which lands just after the run row is written.

    `_run_retraining` records the outcome on the row and only then lets the
    exception reach the job registry -- deliberately, so a crash always leaves
    a record -- which means the row can say "error" a moment before the job
    does.
    """
    assert _wait_for(
        lambda: client.get(f"/jobs/{job_id}").json()["status"] != "running",
        timeout=10,
    ), "the job never settled"
    return client.get(f"/jobs/{job_id}").json()["status"]


def _refresh(client, run_id: int) -> RetrainRun:
    run = client.db.get(RetrainRun, run_id)
    client.db.refresh(run)
    return run


# --- Readiness -------------------------------------------------------------


def test_readiness_reports_the_replay_set_and_the_frozen_holdout(env):
    body = env.get("/retraining/readiness").json()

    assert body["replay_configured"] and body["replay_present"]
    assert body["replay_rows"] == 25
    assert body["holdout_present"] and body["holdout_rows"] == 20
    assert body["base_checkpoint"] == model_registry.BASELINE
    assert body["can_run"] is True
    assert body["blockers"] == [] and body["replay_blocker"] is None


def test_an_unconfigured_replay_path_is_a_visible_state_not_a_silent_run(env):
    env.use_settings(retrain_replay_dir="")

    body = env.get("/retraining/readiness").json()

    assert body["replay_configured"] is False
    assert body["can_run"] is False, "a full run is not possible without replay"
    assert body["can_run_without_replay"] is True, "but a labelled one is"
    assert retraining.REPLAY_SETTING in body["replay_blocker"]
    assert body["blockers"] == [], "nothing else is missing"


def test_a_replay_path_that_is_not_there_is_reported_as_missing(env, tmp_path):
    env.use_settings(retrain_replay_dir=str(tmp_path / "on-the-gpu-box"))

    body = env.get("/retraining/readiness").json()

    assert body["replay_configured"] and not body["replay_present"]
    assert "on-the-gpu-box" in body["replay_blocker"]
    assert body["can_run"] is False


# --- Starting a run --------------------------------------------------------


def test_starting_a_run_returns_a_job_and_records_the_run(env, monkeypatch):
    built = _stub_build(monkeypatch)
    passed = _stub_retrain(monkeypatch, improved=True)

    started = env.post(f"/corrections/batches/{_BATCH}/retrain")

    assert started.status_code == 202, "the work has not happened yet"
    job = started.json()
    assert job["status"] == "running"

    runs = env.get("/retraining/runs").json()
    assert len(runs) == 1
    run = runs[0]
    assert run["batch_id"] == _BATCH
    assert run["job_id"] == job["id"]
    assert run["params"]["scope"] == "all"
    assert run["params"]["epochs"] == 5
    assert run["params"]["replay_dir"] == env.replay_dir
    assert run["params"]["base_checkpoint"] == model_registry.BASELINE

    _finished(env, run["id"])
    assert passed["dataset_dir"].endswith(f"finetune/{_BATCH}-all")
    assert passed["replay_dir"] == env.replay_dir
    assert passed["device"] == "cpu"
    assert built["batch_id"] is None, "the default scope is every correction"


def test_scope_batch_rebuilds_that_batch_alone(env, monkeypatch):
    """The reproducible option: the same batch id rebuilds the same data."""
    built = _stub_build(monkeypatch)
    passed = _stub_retrain(monkeypatch, improved=True)

    env.post(f"/corrections/batches/{_BATCH}/retrain", json={"scope": "batch"})
    run = _finished(env, env.get("/retraining/runs").json()[0]["id"])

    assert built["batch_id"] == _BATCH
    assert built["submitted_only"] is True
    assert passed["dataset_dir"].endswith(f"finetune/{_BATCH}")
    assert run.params_json["scope"] == "batch"
    assert run.checkpoint_name == f"{_BATCH}.pth", (
        "a per-batch candidate must not collide with a cumulative one"
    )


def test_the_two_scopes_leave_distinguishable_rows_and_candidates(env, monkeypatch):
    """Same batch id, different data — the log has to say which was which."""
    _stub_build(monkeypatch)
    _stub_retrain(monkeypatch, improved=True)

    env.post(f"/corrections/batches/{_BATCH}/retrain", json={"scope": "batch"})
    _finished(env, env.get("/retraining/runs").json()[0]["id"])
    env.post(f"/corrections/batches/{_BATCH}/retrain", json={"scope": "all"})
    _finished(env, max(r["id"] for r in env.get("/retraining/runs").json()))

    runs = env.get("/retraining/runs").json()
    assert {r["params"]["scope"] for r in runs} == {"all", "batch"}
    assert {r["batch_id"] for r in runs} == {_BATCH}, "both were launched here"
    assert sorted(r["checkpoint_name"] for r in runs) == [
        f"{_BATCH}-all.pth",
        f"{_BATCH}.pth",
    ]


def test_cumulative_counts_one_edit_per_grade_not_one_per_correction(env):
    """A grade corrected twice is one training row, not two."""
    for batch in ("batch-a", "batch-b"):
        env.db.add(
            CorrectionLog(
                study_id="study-1",
                field="L4-L5/canal_stenosis",  # the SAME grade as the fixture's
                old="Normal/Mild",
                new="Moderate",
                at=datetime.datetime.utcnow(),
                submitted_at=datetime.datetime.utcnow(),
                batch_id=batch,
            )
        )
    env.db.commit()

    body = env.get("/retraining/readiness").json()

    assert body["sealed_batches"] == 3
    assert body["cumulative_corrections"] == 1, (
        "three corrections, all on one grade: the latest edit is the row"
    )


def test_a_run_cannot_start_twice(env, monkeypatch):
    """The second press joins the run in flight; another batch is refused."""
    _stub_build(monkeypatch)
    gate = threading.Event()
    _stub_retrain(monkeypatch, improved=False, gate=gate)

    first = env.post(f"/corrections/batches/{_BATCH}/retrain").json()
    assert _wait_for(lambda: retraining.jobs.running_for("retrain", _BATCH) is not None)

    second = env.post(f"/corrections/batches/{_BATCH}/retrain")
    assert second.status_code == 202
    assert second.json()["id"] == first["id"], (
        "a second press must join the running job, not launch a rival one"
    )

    # A different batch would fight the first run for the same CPU.
    env.db.add(
        CorrectionLog(
            study_id="study-1",
            field="L5-S1/canal_stenosis",
            old="Normal/Mild",
            new="Moderate",
            at=datetime.datetime.utcnow(),
            submitted_at=datetime.datetime.utcnow(),
            batch_id="batch-other",
        )
    )
    env.db.commit()
    other = env.post("/corrections/batches/batch-other/retrain")
    assert other.status_code == 409
    assert _BATCH in other.json()["detail"]

    gate.set()
    assert len(env.get("/retraining/runs").json()) == 1, "only one run was recorded"


def test_a_missing_replay_path_is_refused_and_says_what_to_set(env, monkeypatch):
    _stub_build(monkeypatch)
    _stub_retrain(monkeypatch, improved=True)
    env.use_settings(retrain_replay_dir="")

    refused = env.post(f"/corrections/batches/{_BATCH}/retrain")

    assert refused.status_code == 400
    detail = refused.json()["detail"]
    assert retraining.REPLAY_SETTING in detail
    assert "forget" in detail, "the refusal must say why it matters"
    assert env.get("/retraining/runs").json() == [], "nothing was started"


def test_a_replay_free_run_has_to_be_asked_for_explicitly(env, monkeypatch):
    _stub_build(monkeypatch)
    passed = _stub_retrain(monkeypatch, improved=False)
    env.use_settings(retrain_replay_dir="")

    started = env.post(
        f"/corrections/batches/{_BATCH}/retrain", json={"without_replay": True}
    )

    assert started.status_code == 202
    run = env.get("/retraining/runs").json()[0]
    _finished(env, run["id"])
    assert passed["replay_dir"] is None
    # The recorded parameters must show it was the weaker experiment.
    assert env.get("/retraining/runs").json()[0]["params"]["replay_size"] == 0


def test_a_run_never_changes_which_checkpoint_grades_the_next_patient(
    env, monkeypatch
):
    _stub_build(monkeypatch)
    _stub_retrain(monkeypatch, improved=True)
    before_active = model_registry.active_checkpoint_name()

    env.post(f"/corrections/batches/{_BATCH}/retrain")
    run_id = env.get("/retraining/runs").json()[0]["id"]
    run = _finished(env, run_id)

    assert run.status == "done" and run.improved is True
    assert run.checkpoint_name == f"{_BATCH}-all.pth"
    assert (env.weights_dir / run.checkpoint_name).is_file(), "a candidate exists"
    assert model_registry.active_checkpoint_name() == before_active
    assert not (env.weights_dir / model_registry._POINTER).exists(), (
        "a run must never write the ACTIVE pointer"
    )
    listed = env.get("/retraining/runs").json()[0]
    assert listed["checkpoint_exists"] is True
    assert listed["checkpoint_active"] is False, "it waits for approval on /models"


def test_no_improvement_is_a_finished_run_not_a_failure(env, monkeypatch):
    _stub_build(monkeypatch)
    _stub_retrain(monkeypatch, improved=False)

    env.post(f"/corrections/batches/{_BATCH}/retrain")
    run = _finished(env, env.get("/retraining/runs").json()[0]["id"])

    assert run.status == "done"
    assert run.improved is False
    assert run.checkpoint_name is None
    assert run.error is None
    assert run.after_json["macro_f1"] < run.before_json["macro_f1"]
    assert _job_status(env, run.job_id) == "done", (
        "an honest 'no' is still a successful run"
    )


def test_a_second_run_on_one_batch_does_not_overwrite_the_first_candidate(
    env, monkeypatch
):
    _stub_build(monkeypatch)
    _stub_retrain(monkeypatch, improved=True)

    env.post(f"/corrections/batches/{_BATCH}/retrain")
    first = _finished(env, env.get("/retraining/runs").json()[0]["id"])
    env.post(f"/corrections/batches/{_BATCH}/retrain")
    second_id = max(r["id"] for r in env.get("/retraining/runs").json())
    second = _finished(env, second_id)

    assert first.checkpoint_name == f"{_BATCH}-all.pth"
    assert second.checkpoint_name == f"{_BATCH}-all-run2.pth"
    assert (env.weights_dir / first.checkpoint_name).is_file()


def test_a_batch_with_nothing_trainable_fails_with_a_readable_reason(
    env, monkeypatch
):
    _stub_build(monkeypatch, num_rows=0, skipped=["study-1/L4-L5 (missing mask)"])
    _stub_retrain(monkeypatch, improved=True)

    env.post(f"/corrections/batches/{_BATCH}/retrain")
    run = _finished(env, env.get("/retraining/runs").json()[0]["id"])

    assert run.status == "error"
    assert "0 usable disc" in run.error
    assert run.skipped_json == ["study-1/L4-L5 (missing mask)"]


def test_a_crash_lands_in_the_run_log_and_on_the_job(env, monkeypatch):
    _stub_build(monkeypatch)
    _stub_retrain(monkeypatch, improved=True, boom=RuntimeError("out of memory"))

    env.post(f"/corrections/batches/{_BATCH}/retrain")
    run = _finished(env, env.get("/retraining/runs").json()[0]["id"])

    assert run.status == "error"
    assert "out of memory" in run.error
    assert _job_status(env, run.job_id) == "error"
    assert run.checkpoint_name is None


def test_an_unknown_batch_is_refused_before_anything_starts(env, monkeypatch):
    _stub_build(monkeypatch)
    _stub_retrain(monkeypatch, improved=True)

    response = env.post("/corrections/batches/batch-nope/retrain")

    assert response.status_code == 404
    assert env.get("/retraining/runs").json() == []


def test_a_broken_holdout_set_blocks_every_run(env, monkeypatch, tmp_path):
    _stub_build(monkeypatch)
    _stub_retrain(monkeypatch, improved=True)
    (tmp_path / "holdout_frozen" / freeze_holdout._MANIFEST).unlink()

    readiness = env.get("/retraining/readiness").json()
    refused = env.post(
        f"/corrections/batches/{_BATCH}/retrain", json={"without_replay": True}
    )

    assert readiness["holdout_present"] is False
    assert readiness["can_run_without_replay"] is False
    assert refused.status_code == 409
    assert "held-out" in refused.json()["detail"]


def test_parameters_out_of_range_are_refused(env):
    response = env.post(f"/corrections/batches/{_BATCH}/retrain", json={"epochs": 500})

    assert response.status_code == 422


# --- Progress and restarts -------------------------------------------------


def test_progress_stages_come_from_the_real_scoring_calls(monkeypatch):
    """The bar moves when the run reaches a stage, not when a timer fires."""
    seen: list[tuple[str, int]] = []
    monkeypatch.setattr(retraining.retrain_head, "evaluate", lambda *a, **k: {"x": 1})
    original = retraining.retrain_head.evaluate

    with retraining._epoch_progress(lambda s, p: seen.append((s, p)), epochs=2):
        for _ in range(4):  # before, epoch 1, epoch 2, final
            retraining.retrain_head.evaluate()

    assert retraining.retrain_head.evaluate is original, "the module is put back"
    stages = [s for s, _ in seen]
    assert "Scoring the checkpoint in service on the held-out set" == stages[0]
    assert any("epoch 1 of up to 2" in s for s in stages)
    assert any("round 3 of up to 3" in s for s in stages)
    percents = [p for _, p in seen]
    assert percents == sorted(percents) and max(percents) <= 92


def test_runs_left_running_by_a_restart_are_closed_out(env):
    """Jobs live in memory: after a restart nothing will ever finish that row."""
    env.db.add(
        RetrainRun(
            batch_id=_BATCH,
            status="running",
            job_id="gone-with-the-server",
            started_at=datetime.datetime.utcnow(),
            params_json={},
        )
    )
    env.db.commit()

    # Opening the page is what heals it: readiness reconciles before answering.
    assert env.get("/retraining/readiness").json()["can_run"] is True, (
        "a stale row must not block every later run"
    )

    run = env.db.query(RetrainRun).one()
    env.db.refresh(run)
    assert run.status == "interrupted"
    assert run.finished_at is not None
    assert "restarted" in run.error


def test_a_run_that_is_really_going_is_never_closed_out(env, monkeypatch):
    """The bug this guards: a second process opening the same database.

    The reconciliation used to run at startup and stamp every "running" row as
    interrupted. The test suite opens the production database through the app's
    lifespan, so it did exactly that to a run that was still training.
    """
    _stub_build(monkeypatch)
    gate = threading.Event()
    _stub_retrain(monkeypatch, improved=False, gate=gate)

    job = env.post(f"/corrections/batches/{_BATCH}/retrain").json()
    assert _wait_for(lambda: retraining.jobs.running_for("retrain", _BATCH) is not None)

    closed = mark_interrupted_runs(env.db, retraining._job_is_alive)
    readiness = env.get("/retraining/readiness").json()

    assert closed == 0
    assert readiness["running_batch_id"] == _BATCH
    run = env.db.query(RetrainRun).one()
    env.db.refresh(run)
    assert run.status == "running" and run.error is None
    assert run.job_id == job["id"]

    gate.set()
