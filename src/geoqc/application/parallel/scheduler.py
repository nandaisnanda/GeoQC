"""Deterministic task planning and conservative worker selection."""

import os
from collections.abc import Iterable
from pathlib import Path

from geoqc.application.parallel.models import ParallelTask, WorkerPolicy


class TaskScheduler:
    """Assign stable sequence numbers and choose bounded concurrency."""

    def __init__(self, policy: WorkerPolicy | None = None) -> None:
        self._policy = policy or WorkerPolicy()

    def schedule(self, sources: Iterable[Path]) -> tuple[ParallelTask, ...]:
        return tuple(ParallelTask(index, source) for index, source in enumerate(sources))

    def worker_count(
        self,
        task_count: int,
        *,
        cpu_count: int | None = None,
        available_memory: int | None = None,
        requested_workers: int | None = None,
        multiprocessing_safe: bool = True,
    ) -> int:
        if task_count < 1 or not multiprocessing_safe:
            return 1
        cpus = max(1, cpu_count if cpu_count is not None else (os.cpu_count() or 1))
        cpu_budget = max(1, cpus - self._policy.reserve_cpus)
        memory_budget = task_count
        if available_memory is not None:
            usable = int(available_memory * self._policy.memory_utilization)
            memory_budget = max(1, usable // self._policy.estimated_bytes_per_worker)
        requested = requested_workers or self._policy.maximum_workers
        if requested < 1:
            raise ValueError("requested_workers must be positive")
        return max(
            1,
            min(task_count, requested, self._policy.maximum_workers, cpu_budget, memory_budget),
        )
