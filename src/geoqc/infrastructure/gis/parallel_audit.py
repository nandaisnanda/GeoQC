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
from geoqc.application.streaming.models import DatasetSource
from geoqc.infrastructure.benchmarking import ProcessBenchmarkRecorder
from geoqc.infrastructure.gis.automatic_geometry_engine import AutomaticGeometryEngine
from geoqc.infrastructure.gis.streaming import default_reader_registry


@dataclass(frozen=True, slots=True)
class DatasetAudit:
    """Serializable audit value returned from one worker process."""

    result: GeometryAuditResult
    decision: EngineDecision
    benchmark: BenchmarkMetrics | None = None


@dataclass(frozen=True, slots=True)
class DatasetAuditWorker:
    """Pickle-safe configurable worker used by spawned process pools."""

    benchmark_enabled: bool = False
    chunk_size: int = 16_384
    worker_count: int = 1
    rule_count: int = 0

    def __call__(self, path: Path) -> DatasetAudit:
        source = DatasetSource(path=path)
        reader = default_reader_registry().resolve(source)
        engine = AutomaticGeometryEngine(reader, chunk_size=self.chunk_size)
        recorder = ProcessBenchmarkRecorder() if self.benchmark_enabled else NoOpBenchmarkRecorder()
        value, metrics = recorder.measure(
            lambda: engine.run(source),
            BenchmarkContext(
                source=str(path),
                chunk_size=self.chunk_size,
                worker_count=self.worker_count,
                rule_count=self.rule_count,
            ),
            _describe_audit,
        )
        result, decision = value
        return DatasetAudit(result=result, decision=decision, benchmark=metrics)


def audit_dataset(path: Path) -> DatasetAudit:
    """Build process-local GIS adapters and audit one dataset read-only."""
    return DatasetAuditWorker()(path)


def _describe_audit(
    value: tuple[GeometryAuditResult, EngineDecision],
) -> tuple[int, int, str]:
    result, decision = value
    return result.feature_count, result.feature_count, decision.engine
