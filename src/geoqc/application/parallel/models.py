"""Immutable scheduling and monitoring values for parallel batch execution."""

from dataclasses import dataclass
from pathlib import Path

from geoqc.domain.models import BatchItemStatus


@dataclass(frozen=True, slots=True)
class ParallelTask:
    """One stable, pickle-safe unit submitted to a worker."""

    sequence: int
    source: Path

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("task sequence cannot be negative")


@dataclass(frozen=True, slots=True)
class ParallelProgress:
    """Parent-process monitoring snapshot for a parallel batch."""

    completed: int
    total: int
    current_sources: tuple[str, ...] = ()
    source: str | None = None
    status: BatchItemStatus | None = None
    elapsed_seconds: float = 0.0
    estimated_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.total < 0 or not 0 <= self.completed <= self.total:
            raise ValueError("parallel progress must be between zero and total")
        if self.elapsed_seconds < 0:
            raise ValueError("elapsed_seconds cannot be negative")
        if self.estimated_seconds is not None and self.estimated_seconds < 0:
            raise ValueError("estimated_seconds cannot be negative")
        if (self.source is None) is not (self.status is None):
            raise ValueError("source and status must be provided together")

    @property
    def remaining(self) -> int:
        return self.total - self.completed


@dataclass(frozen=True, slots=True)
class WorkerPolicy:
    """Resource policy used to cap process-level concurrency."""

    maximum_workers: int = 8
    reserve_cpus: int = 1
    estimated_bytes_per_worker: int = 512 * 1024 * 1024
    memory_utilization: float = 0.75

    def __post_init__(self) -> None:
        if self.maximum_workers < 1:
            raise ValueError("maximum_workers must be positive")
        if self.reserve_cpus < 0:
            raise ValueError("reserve_cpus cannot be negative")
        if self.estimated_bytes_per_worker < 1:
            raise ValueError("estimated_bytes_per_worker must be positive")
        if not 0 < self.memory_utilization <= 1:
            raise ValueError("memory_utilization must be in (0, 1]")
