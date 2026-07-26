"""Tests for the background-job registry behind long grading runs.

The properties that matter operationally: a failure must look like a failure
rather than a hang, two runs on one study must not race over the same output
files, and a client polling after the fact must still learn the outcome.
"""

import threading
import time

import pytest

from app.jobs import JobRegistry


def _wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_a_job_runs_and_reports_done():
    registry = JobRegistry()
    ran = threading.Event()

    job = registry.start("test", "target-1", lambda progress: ran.set())

    assert _wait_for(lambda: registry.get(job.id).status == "done")
    assert ran.is_set()
    assert registry.get(job.id).percent == 100


def test_progress_callback_updates_stage_and_percent():
    registry = JobRegistry()
    released = threading.Event()

    def work(progress):
        progress("Segmenting", 10)
        released.wait(timeout=5)

    job = registry.start("test", "target-1", work)
    assert _wait_for(lambda: registry.get(job.id).stage == "Segmenting")
    assert registry.get(job.id).percent == 10
    assert registry.get(job.id).status == "running"
    released.set()


def test_a_failure_is_reported_not_swallowed():
    """A crashed job must be distinguishable from one still working."""
    registry = JobRegistry()

    def work(progress):
        raise RuntimeError("segmentation binary missing")

    job = registry.start("test", "target-1", work)

    assert _wait_for(lambda: registry.get(job.id).status == "error")
    finished = registry.get(job.id)
    assert "segmentation binary missing" in finished.error
    assert finished.finished_at is not None


def test_percent_is_clamped_to_a_sane_range():
    registry = JobRegistry()
    done = threading.Event()

    def work(progress):
        progress("weird", 300)
        progress("weirder", -20)
        done.set()

    registry.start("test", "target-1", work)
    assert _wait_for(done.is_set)


def test_running_for_finds_an_in_flight_job_on_the_same_target():
    """Two grading runs on one study would race over the same result files."""
    registry = JobRegistry()
    released = threading.Event()

    job = registry.start("grade_full", "study-1", lambda p: released.wait(timeout=5))
    assert _wait_for(lambda: registry.running_for("grade_full", "study-1") is not None)

    found = registry.running_for("grade_full", "study-1")
    assert found.id == job.id
    assert registry.running_for("grade_full", "study-2") is None
    assert registry.running_for("other_kind", "study-1") is None

    released.set()
    assert _wait_for(lambda: registry.get(job.id).status == "done")
    assert registry.running_for("grade_full", "study-1") is None, (
        "a finished job must not block the next run"
    )


def test_finished_jobs_stay_queryable_for_late_pollers():
    registry = JobRegistry()

    job = registry.start("test", "target-1", lambda p: None)
    assert _wait_for(lambda: registry.get(job.id).status == "done")

    time.sleep(0.05)
    assert registry.get(job.id) is not None, "a client polling late still needs the outcome"


def test_unknown_job_id_is_none():
    assert JobRegistry().get("nope") is None


def test_old_finished_jobs_are_evicted():
    registry = JobRegistry()
    registry.MAX_FINISHED = 3

    ids = []
    for _ in range(6):
        job = registry.start("test", "t", lambda p: None)
        assert _wait_for(lambda: registry.get(job.id) is None or registry.get(job.id).status == "done")
        ids.append(job.id)

    alive = [i for i in ids if registry.get(i) is not None]
    assert len(alive) <= registry.MAX_FINISHED + 1
    assert ids[-1] in alive, "the most recent job must survive eviction"


def test_elapsed_seconds_stops_when_the_job_finishes():
    registry = JobRegistry()

    job = registry.start("test", "target-1", lambda p: None)
    assert _wait_for(lambda: registry.get(job.id).status == "done")

    first = registry.get(job.id).elapsed_seconds
    time.sleep(0.05)
    assert registry.get(job.id).elapsed_seconds == pytest.approx(first)
