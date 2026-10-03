"""Portable result models for public dataset-level audits."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from geoqc.domain.rules import Severity


class CheckStatus(StrEnum):
    """Outcome of one independently reportable audit check."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class AuditDatasetMetadata:
    """Stable metadata describing the audited dataset and execution engine."""

    path: str
    layer: str | None
    driver: str
    crs: str | None
    feature_count: int
    geometry_column: str
    size_bytes: int
    engine: str

    def to_dict(self) -> dict[str, object]:
        """Return metadata in deterministic field order."""
        return {
            "path": self.path,
            "layer": self.layer,
            "driver": self.driver,
            "crs": self.crs,
            "feature_count": self.feature_count,
            "geometry_column": self.geometry_column,
            "size_bytes": self.size_bytes,
            "engine": self.engine,
        }


@dataclass(frozen=True, slots=True)
class AuditIssue:
    """One actionable issue normalized across existing GeoQC services."""

    code: str
    message: str
    severity: Severity
    recommendation: str
    feature_indices: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        for name in ("code", "message", "recommendation"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        if any(index < 0 for index in self.feature_indices):
            raise ValueError("feature indices must be non-negative")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible issue in deterministic field order."""
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "recommendation": self.recommendation,
            "feature_indices": list(self.feature_indices),
        }


@dataclass(frozen=True, slots=True)
class AuditCheckResult:
    """Result of one geometry, CRS, schema, topology, or spatial check."""

    name: str
    status: CheckStatus
    issues: tuple[AuditIssue, ...] = ()
    reason: str | None = None
    counts: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("check name must not be empty")
        if self.status is CheckStatus.SKIPPED and not self.reason:
            raise ValueError("skipped checks require a reason")
        if self.status is CheckStatus.ERROR and not self.reason:
            raise ValueError("errored checks require a reason")
        if self.status is CheckStatus.PASSED and self.issues:
            raise ValueError("passed checks cannot contain issues")
        if self.status is CheckStatus.FAILED and not self.issues:
            raise ValueError("failed checks require at least one issue")
        normalized_counts = dict(sorted(self.counts.items()))
        if not normalized_counts:
            for issue in self.issues:
                normalized_counts[issue.code] = normalized_counts.get(issue.code, 0) + 1
        if any(not name.strip() or count < 0 for name, count in normalized_counts.items()):
            raise ValueError("issue counts require non-empty names and non-negative values")
        object.__setattr__(self, "counts", normalized_counts)

    @property
    def issue_count(self) -> int:
        return sum(self.counts.values()) if self.counts else len(self.issues)

    @property
    def feature_indices(self) -> tuple[int, ...]:
        return tuple(sorted({index for issue in self.issues for index in issue.feature_indices}))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible check result in deterministic field order."""
        return {
            "name": self.name,
            "status": self.status.value,
            "reason": self.reason,
            "issue_count": self.issue_count,
            "issue_counts": dict(self.counts),
            "feature_indices": list(self.feature_indices),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True, slots=True)
class DatasetAuditReport:
    """Unified, deterministic report returned by :func:`geoqc.audit_dataset`."""

    metadata: AuditDatasetMetadata
    checks: tuple[AuditCheckResult, ...]
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        names = tuple(check.name for check in self.checks)
        if len(names) != len(set(names)):
            raise ValueError("check names must be unique")

    @property
    def status(self) -> CheckStatus:
        statuses = {check.status for check in self.checks}
        if CheckStatus.ERROR in statuses:
            return CheckStatus.ERROR
        if CheckStatus.FAILED in statuses:
            return CheckStatus.FAILED
        if CheckStatus.PASSED in statuses:
            return CheckStatus.PASSED
        return CheckStatus.SKIPPED

    @property
    def issue_count(self) -> int:
        return sum(check.issue_count for check in self.checks)

    @property
    def feature_indices(self) -> tuple[int, ...]:
        return tuple(sorted({index for check in self.checks for index in check.feature_indices}))

    def check(self, name: str) -> AuditCheckResult:
        """Return a named check or raise ``KeyError`` when it is absent."""
        selected = next((check for check in self.checks if check.name == name), None)
        if selected is None:
            raise KeyError(name)
        return selected

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible representation."""
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "issue_count": self.issue_count,
            "feature_indices": list(self.feature_indices),
            "metadata": self.metadata.to_dict(),
            "checks": [check.to_dict() for check in self.checks],
        }
