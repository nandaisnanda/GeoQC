"""Portable result models for public dataset-level audits."""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from geoqc.domain.rules import Severity

if TYPE_CHECKING:
    from geoqc.domain.models.quality_workflow import DatasetAuditResult


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
    """Deprecated input shape accepted by the P0 compatibility adapter."""

    code: str
    message: str
    severity: Severity
    recommendation: str
    feature_indices: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        warnings.warn(
            "AuditIssue is deprecated; use DatasetIssue from geoqc instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        for name in ("code", "message", "recommendation"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        if any(index < 0 for index in self.feature_indices):
            raise ValueError("feature indices must be non-negative")

    def to_dict(self) -> dict[str, object]:
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
    issues: tuple[Any, ...] = ()
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
        indices: set[int] = set()
        for issue in self.issues:
            legacy = getattr(issue, "feature_indices", ())
            indices.update(int(index) for index in legacy)
            for attribute in ("feature_index", "related_feature_index"):
                index = getattr(issue, attribute, None)
                if index is not None:
                    indices.add(int(index))
        return tuple(sorted(indices))

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


def DatasetAuditReport(  # noqa: N802
    metadata: AuditDatasetMetadata,
    checks: tuple[AuditCheckResult, ...],
    schema_version: str = "1.0",
) -> DatasetAuditResult:
    """Construct the canonical result from the deprecated P0 report shape."""
    warnings.warn(
        "DatasetAuditReport is deprecated; use DatasetAuditResult returned by "
        "geoqc.audit_dataset().",
        DeprecationWarning,
        stacklevel=2,
    )
    from geoqc.domain.models.quality_workflow import (
        CrsGuardResult,
        CrsUnitStatus,
        DatasetAuditResult,
    )

    return DatasetAuditResult(
        dataset_name=metadata.layer or metadata.path,
        preset=None,
        feature_count=metadata.feature_count,
        issues=(),
        crs_guard=CrsGuardResult(
            metadata.crs,
            CrsUnitStatus.UNKNOWN if metadata.crs is None else CrsUnitStatus.SAFE,
            None,
            False,
            "Compatibility result constructed from DatasetAuditReport.",
        ),
        category_scores=(),
        quality_score=100.0,
        schema_version=schema_version,
        metadata=metadata,
        checks=checks,
    )
