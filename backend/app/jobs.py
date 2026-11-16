"""In-process registry for long-running background work.

Full grading can take many minutes on CPU, too long to hold an HTTP request
open behind a reverse proxy. The request starts a job and returns immediately;
the client polls for stage and progress. Jobs persist their own results, so a
client that missed the end of a job can fetch the outcome from the normal GET
endpoints.

Deliberately in-memory and single-process: jobs do not survive a restart, and
`GET /jobs/{id}` returns 404 for an unknown id.
"""

from __future__ import annotations

import datetime
import logging
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Callable, Protocol

logger = logging.getLogger("uvicorn.error")


class ProgressFn(Protocol):
    """Called by long-running work to report which stage it reached."""

    def __call__(self, stage: str, percent: int, **partial) -> None: ...


@dataclass
class Job:
    id: str
    kind: str
    target_id: str
    status: str = "running"  # running | done | error
    stage: str = "Starting"
    percent: int = 0
    error: str | None = None
    #: Intermediate results the client may show early (e.g. segmentation
    #: labels before grading finishes).
    partial: dict = field(default_factory=dict)
    started_at: datetime.datetime = field(default_factory=datetime.datetime.utcnow)
    finished_at: datetime.datetime | None = None

    @property
    def elapsed_seconds(self) -> float:
        end = self.finished_at or datetime.datetime.utcnow()
        return (end - self.started_at).total_seconds()


class JobRegistry:
    """Thread-safe job store. One instance per process (see `jobs` below)."""

    #: Finished jobs are kept so a client that polls late still sees the
    #: outcome; beyond this many, the oldest finished ones are dropped.
    MAX_FINISHED = 50

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def running_for(self, kind: str, target_id: str) -> Job | None:
        """An in-flight job for this target, if any.

        Used to refuse a second concurrent grading of the same study, since
        both runs would write the same result files and annotation.
        """
        with self._lock:
            for job in self._jobs.values():
                if (
                    job.kind == kind
                    and job.target_id == target_id
                    and job.status == "running"
                ):
                    return job
        return None

    def start(
        self,
        kind: str,
        target_id: str,
        work: Callable[[ProgressFn], None],
    ) -> Job:
        """Run `work` on a background thread, passing it a progress callback."""
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, target_id=target_id)
        with self._lock:
            self._jobs[job.id] = job
            self._evict_old_locked()

        def report(stage: str, percent: int, **partial) -> None:
            with self._lock:
                job.stage = stage
                job.percent = max(0, min(100, percent))
                job.partial.update(partial)

        def run() -> None:
            started = time.monotonic()
            logger.info("[job %s %s] started (%s)", kind, target_id, job.id)
            try:
                work(report)
            except Exception as exc:
                # Full traceback to the server log, tagged with the target id;
                # the client gets the message. A failed job must never look hung.
                logger.error(
                    "[job %s %s] FAILED after %.0fs at stage %r\n%s",
                    kind,
                    target_id,
                    time.monotonic() - started,
                    job.stage,
                    traceback.format_exc(),
                )
                with self._lock:
                    job.status = "error"
                    job.error = f"{type(exc).__name__}: {exc}"
                    job.finished_at = datetime.datetime.utcnow()
            else:
                logger.info(
                    "[job %s %s] done in %.0fs", kind, target_id, time.monotonic() - started
                )
                with self._lock:
                    job.status = "done"
                    job.stage = "Finished"
                    job.percent = 100
                    job.finished_at = datetime.datetime.utcnow()

        threading.Thread(target=run, name=f"job-{kind}-{job.id}", daemon=True).start()
        return job

    def _evict_old_locked(self) -> None:
        finished = sorted(
            (j for j in self._jobs.values() if j.status != "running"),
            key=lambda j: j.finished_at or j.started_at,
        )
        for job in finished[: max(0, len(finished) - self.MAX_FINISHED)]:
            self._jobs.pop(job.id, None)


#: Process-wide registry.
jobs = JobRegistry()
