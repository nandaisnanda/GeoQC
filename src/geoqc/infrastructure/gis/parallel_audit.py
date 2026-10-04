"""Process-isolated geometry audit worker composition."""

from dataclasses import dataclass
from pathlib import Path

from geoqc.application.benchmarking import (
    BenchmarkContext,
    BenchmarkMetrics,
    NoOpBenchmarkRecorder,
)
from geoqc.application.engine_selection import EngineDecision
from geoqc.application.streaming.geometry import GeometryAuditResult
from geoqc.domain.models import DatasetAuditResult
from geoqc.infrastructure.benchmarking import ProcessBenchmarkRecorder
from geoqc.infrastructure.gis.dataset_audit import _audit_dataset_with_geometry


@dataclass(frozen=True, slots=True)
class DatasetAudit:
    """Serializable audit value returned from one worker process."""

    result: GeometryAuditResult
    decision: EngineDecision
    benchmark: BenchmarkMetrics | None = None
    report: DatasetAuditResult | None = None


@dataclass(frozen=True, slots=True)
class DatasetAuditWorker:
    """Pickle-safe configurable worker used by spawned process pools."""

    benchmark_enabled: bool = False
    chunk_size: int = 16_384
    worker_count: int = 1
    rule_count: int = 0

    def __call__(self, path: Path) -> DatasetAudit:
        recorder = ProcessBenchmarkRecorder() if self.benchmark_enabled else NoOpBenchmarkRecorder()
        value, metrics = recorder.measure(
            lambda: _audit_dataset_with_geometry(path, chunk_size=self.chunk_size),
            BenchmarkContext(
                source=str(path),
                chunk_size=self.chunk_size,
                worker_count=self.worker_count,
                rule_count=self.rule_count,
            ),
            _describe_unified_audit,
        )
        report, result, decision = value
        return DatasetAudit(result=result, decision=decision, benchmark=metrics, report=report)


def audit_dataset_worker(path: Path) -> DatasetAudit:
    """Build process-local GIS adapters and audit one dataset read-only."""
    return DatasetAuditWorker()(path)


# Internal compatibility name used by P0 batch integrations.
audit_dataset = audit_dataset_worker


def _describe_audit(
    value: tuple[GeometryAuditResult, EngineDecision],
) -> tuple[int, int, str]:
    result, decision = value
    return result.feature_count, result.feature_count, decision.engine


def _describe_unified_audit(
    value: tuple[DatasetAuditResult, GeometryAuditResult, EngineDecision],
) -> tuple[int, int, str]:
    report, _, decision = value
    return report.metadata.feature_count, report.metadata.feature_count, decision.engine
