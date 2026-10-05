"""Thread-safe process-local execution for large dataset validation jobs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from enum import StrEnum
from secrets import token_urlsafe
from threading import RLock
from time import time

from geoqc.interfaces.api.metrics import MetricsRegistry


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


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
        retention_seconds: int,
        metrics: MetricsRegistry,
        clock: Callable[[], float] = time,
    ) -> None:
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="geoqc-job")
        self._retention = retention_seconds
        self._metrics = metrics
        self._clock = clock
        self._records: dict[str, JobRecord] = {}
        self._lock = RLock()

    def submit(self, request_id: str, operation: Callable[[], Mapping[str, object]]) -> JobRecord:
        self.cleanup()
        now = self._clock()
        job_id = token_urlsafe(24)
        record = JobRecord(job_id, JobState.QUEUED, request_id, now, now)
        with self._lock:
            self._records[job_id] = record
        self._metrics.job_state(JobState.QUEUED.value)
        self._executor.submit(self._run, job_id, operation)
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
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _run(self, job_id: str, operation: Callable[[], Mapping[str, object]]) -> None:
        self._transition(job_id, JobState.RUNNING)
        try:
            result = operation()
        except Exception:
            self._transition(job_id, JobState.FAILED, error="Job processing failed.")
            self._metrics.event("audit_failed")
            return
        self._transition(job_id, JobState.SUCCEEDED, result=result)
        self._metrics.event("audit_succeeded")

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
            self._records[job_id] = replace(
                current,
                state=state,
                updated_at=self._clock(),
                result=result,
                error=error,
            )
        self._metrics.job_state(state.value)
