"""Framework-independent benchmark values and report aggregation."""

from dataclasses import asdict, dataclass
from typing import Any

SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class BenchmarkContext:
    """Static audit configuration attached to one benchmark record."""

    source: str
    chunk_size: int
    worker_count: int
    rule_count: int = 0

    def __post_init__(self) -> None:
        if self.chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        if self.worker_count < 1:
            raise ValueError("worker_count must be positive")
        if self.rule_count < 0:
            raise ValueError("rule_count must not be negative")


@dataclass(frozen=True, slots=True)
class BenchmarkMetrics:
    """Resource metrics captured around one dataset audit."""

    source: str
    runtime_seconds: float
    cpu_time_seconds: float
    cpu_usage_percent: float
    memory_usage_bytes: int
    peak_memory_bytes: int
    feature_count: int
    geometry_count: int
    rule_count: int
    engine: str
    chunk_size: int
    worker_count: int

    def __post_init__(self) -> None:
        numeric = (
            self.runtime_seconds,
            self.cpu_time_seconds,
            self.cpu_usage_percent,
            self.memory_usage_bytes,
            self.peak_memory_bytes,
            self.feature_count,
            self.geometry_count,
            self.rule_count,
        )
        if any(value < 0 for value in numeric):
            raise ValueError("benchmark metrics must not be negative")
        if self.chunk_size < 1 or self.worker_count < 1:
            raise ValueError("chunk_size and worker_count must be positive")
        if not self.engine.strip():
            raise ValueError("engine must not be empty")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation with stable field names."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BenchmarkSummary:
    audit_count: int
    runtime_seconds: float
    cpu_time_seconds: float
    average_cpu_usage_percent: float
    memory_usage_bytes: int
    peak_memory_bytes: int
    feature_count: int
    geometry_count: int
    rule_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """Ordered benchmark records and their aggregate summary."""

    records: tuple[BenchmarkMetrics, ...] = ()

    @property
    def summary(self) -> BenchmarkSummary:
        count = len(self.records)
        return BenchmarkSummary(
            audit_count=count,
            runtime_seconds=sum(record.runtime_seconds for record in self.records),
            cpu_time_seconds=sum(record.cpu_time_seconds for record in self.records),
            average_cpu_usage_percent=(
                sum(record.cpu_usage_percent for record in self.records) / count if count else 0.0
            ),
            memory_usage_bytes=sum(record.memory_usage_bytes for record in self.records),
            peak_memory_bytes=max((record.peak_memory_bytes for record in self.records), default=0),
            feature_count=sum(record.feature_count for record in self.records),
            geometry_count=sum(record.geometry_count for record in self.records),
            rule_count=sum(record.rule_count for record in self.records),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "summary": self.summary.to_dict(),
            "records": [record.to_dict() for record in self.records],
        }
