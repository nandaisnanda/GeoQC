"""Thread-safe process-local execution for large dataset validation jobs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from enum import StrEnum
from secrets import token_urlsafe
from threading import BoundedSemaphore, RLock
from time import time

from geoqc.interfaces.api.metrics import MetricsRegistry


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobQueueFullError(RuntimeError):
    """Raised when the bounded process-local executor has no free capacity."""


@dataclass(frozen=True, slots=True)
class JobRecord:
    job_id: str
    state: JobState
    request_id: str
    created_at: float
    updated_at: float
    result: Mapping[str, object] | None = None
    error: str | None = None


class JobManager:
    """Bounded in-memory job registry backed by a local thread pool."""

    def __init__(
        self,
        *,
        workers: int,
        queue_capacity: int = 32,
        max_records: int = 10_000,
        retention_seconds: int,
        metrics: MetricsRegistry,
        clock: Callable[[], float] = time,
    ) -> None:
        if workers <= 0 or queue_capacity <= 0 or max_records <= 0:
            raise ValueError("workers, queue_capacity, and max_records must be greater than zero")
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="geoqc-job")
        self._capacity = BoundedSemaphore(workers + queue_capacity)
        self._retention = retention_seconds
        self._max_records = max_records
        self._metrics = metrics
        self._clock = clock
        self._records: dict[str, JobRecord] = {}
        self._lock = RLock()

    def submit(self, request_id: str, operation: Callable[[], Mapping[str, object]]) -> JobRecord:
        self.cleanup()
        if not self._capacity.acquire(blocking=False):
            raise JobQueueFullError("Job queue is full.")
        now = self._clock()
        with self._lock:
            if len(self._records) >= self._max_records:
                self._capacity.release()
                raise JobQueueFullError("Job registry is full.")
            job_id = token_urlsafe(24)
            while job_id in self._records:
                job_id = token_urlsafe(24)
            record = JobRecord(job_id, JobState.QUEUED, request_id, now, now)
            self._records[job_id] = record
        self._metrics.job_state(JobState.QUEUED.value)
        try:
            self._executor.submit(self._run, job_id, operation)
        except RuntimeError:
            with self._lock:
                del self._records[job_id]
            self._capacity.release()
            raise
        return record

    def get(self, job_id: str) -> JobRecord | None:
        self.cleanup()
        with self._lock:
            return self._records.get(job_id)

    def cleanup(self) -> int:
        cutoff = self._clock() - self._retention
        with self._lock:
            expired = [
                job_id
                for job_id, record in self._records.items()
                if record.updated_at < cutoff
                and record.state in {JobState.SUCCEEDED, JobState.FAILED}
            ]
            for job_id in expired:
                del self._records[job_id]
        return len(expired)

    def close(self) -> None:
        # Let admitted work reach its operation-level ``finally`` cleanup.
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _run(self, job_id: str, operation: Callable[[], Mapping[str, object]]) -> None:
        started = self._clock()
        self._transition(job_id, JobState.RUNNING)
        try:
            result = operation()
        except Exception:
            self._transition(job_id, JobState.FAILED, error="Job processing failed.")
            self._metrics.event("audit_failed")
            self._metrics.observe_job_duration(JobState.FAILED.value, self._clock() - started)
        else:
            self._transition(job_id, JobState.SUCCEEDED, result=result)
            self._metrics.event("audit_succeeded")
            self._metrics.observe_job_duration(JobState.SUCCEEDED.value, self._clock() - started)
        finally:
            self._capacity.release()

    def _transition(
        self,
        job_id: str,
        state: JobState,
        *,
        result: Mapping[str, object] | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            current = self._records[job_id]
            allowed = {
                JobState.QUEUED: frozenset({JobState.RUNNING}),
                JobState.RUNNING: frozenset({JobState.SUCCEEDED, JobState.FAILED}),
                JobState.SUCCEEDED: frozenset(),
                JobState.FAILED: frozenset(),
            }
            if state not in allowed[current.state]:
                raise RuntimeError(f"invalid job transition: {current.state} to {state}")
            self._records[job_id] = replace(
                current,
                state=state,
                updated_at=self._clock(),
                result=result,
                error=error,
            )
        self._metrics.job_state(state.value)
