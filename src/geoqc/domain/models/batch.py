"""Framework-independent outcomes and progress events for batch processing."""

from dataclasses import dataclass
from enum import StrEnum


class BatchItemStatus(StrEnum):
    """Terminal state of one dataset in a batch."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BatchItemResult[ResultT]:
    """Outcome produced for one discovered dataset."""

    source: str
    status: BatchItemStatus
    value: ResultT | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("batch item source must not be empty")
        if self.status is BatchItemStatus.SUCCEEDED and self.error is not None:
            raise ValueError("a successful batch item must not contain an error")
        if self.status is BatchItemStatus.FAILED and not self.error:
            raise ValueError("a failed batch item must contain an error")


@dataclass(frozen=True, slots=True)
class BatchResult[ResultT]:
    """Complete outcomes for a deterministic batch run."""

    items: tuple[BatchItemResult[ResultT], ...] = ()

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def succeeded(self) -> int:
        return sum(item.status is BatchItemStatus.SUCCEEDED for item in self.items)

    @property
    def failed(self) -> int:
        return self.total - self.succeeded

    @property
    def is_successful(self) -> bool:
        return self.failed == 0


@dataclass(frozen=True, slots=True)
class BatchProgress:
    """Snapshot emitted before processing and after every dataset."""

    completed: int
    total: int
    source: str | None = None
    status: BatchItemStatus | None = None

    def __post_init__(self) -> None:
        if self.total < 0 or not 0 <= self.completed <= self.total:
            raise ValueError("batch progress must be between zero and total")
        if self.completed == 0 and (self.source is not None or self.status is not None):
            raise ValueError("initial batch progress must not identify an item")
        if self.completed > 0 and (not self.source or self.status is None):
            raise ValueError("completed batch progress must identify the processed item")
