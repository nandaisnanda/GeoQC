"""Process-isolated canonical dataset audit worker composition."""

from dataclasses import dataclass
from pathlib import Path

from geoqc.application.benchmarking import (
    BenchmarkContext,
    BenchmarkMetrics,
    NoOpBenchmarkRecorder,
)
from geoqc.application.engine_selection import DatasetProfile, EngineDecision
from geoqc.domain.models import DatasetAuditResult
from geoqc.infrastructure.benchmarking import ProcessBenchmarkRecorder
from geoqc.infrastructure.gis.dataset_workflow import audit_dataset as canonical_audit_dataset


@dataclass(frozen=True, slots=True)
class DatasetAudit:
    """Serializable canonical audit value returned from one worker process."""

    result: DatasetAuditResult
    decision: EngineDecision
    benchmark: BenchmarkMetrics | None = None

    @property
    def report(self) -> DatasetAuditResult:
        """Compatibility view retained for callers that used the P0 field name."""
        return self.result


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
            lambda: _run_canonical(path),
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


def audit_dataset_worker(path: Path) -> DatasetAudit:
    """Build process-local GIS adapters and audit one dataset read-only."""
    return DatasetAuditWorker()(path)


# Internal compatibility name used by existing batch integrations.
audit_dataset = audit_dataset_worker


def _run_canonical(path: Path) -> tuple[DatasetAuditResult, EngineDecision]:
    result = canonical_audit_dataset(path)
    metadata = result.metadata
    decision = EngineDecision(
        engine=metadata.engine,
        reasons=("Canonical geoqc.audit_dataset workflow.",),
        profile=DatasetProfile(
            driver=metadata.driver,
            size_bytes=metadata.size_bytes,
            feature_count=metadata.feature_count,
            estimated_memory_bytes=0,
            available_memory_bytes=None,
        ),
    )
    return result, decision


def _describe_audit(
    value: tuple[DatasetAuditResult, EngineDecision],
) -> tuple[int, int, str]:
    result, decision = value
    return result.feature_count, result.feature_count, decision.engine
