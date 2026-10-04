"""Canonical immutable dataset audit result and export port."""

from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import Protocol

from geoqc.domain.models.dataset_audit import (
    AuditCheckResult,
    AuditDatasetMetadata,
    CheckStatus,
)
from geoqc.domain.models.quality_profile import QualityGatePolicy, QualityPreset
from geoqc.domain.models.scoring import (
    CategoryScore,
    CrsGuardResult,
    CrsUnitStatus,
    ScoreDeduction,
)
from geoqc.domain.models.topology import DatasetIssue, IssueGeometryKind
from geoqc.domain.rules.models import Severity


class AuditResultExporter(Protocol):
    """Output port implemented by infrastructure for an immutable audit result."""

    def json(self, result: "DatasetAuditResult", destination: Path, *, overwrite: bool) -> Path: ...

    def html(self, result: "DatasetAuditResult", destination: Path, *, overwrite: bool) -> Path: ...

    def findings(
        self, result: "DatasetAuditResult", destination: Path, *, overwrite: bool
    ) -> Path: ...


@dataclass(frozen=True, slots=True)
class DatasetAuditResult:
    dataset_name: str
    preset: QualityPreset | None
    feature_count: int
    issues: tuple[DatasetIssue, ...]
    crs_guard: CrsGuardResult
    category_scores: tuple[CategoryScore, ...]
    quality_score: float
    score_deductions: tuple[ScoreDeduction, ...] = ()
    profile_name: str | None = None
    schema_version: str = "1.0"
    metadata: AuditDatasetMetadata = field(
        default_factory=lambda: AuditDatasetMetadata(
            "", None, "memory", None, 0, "geometry", 0, "in-memory"
        )
    )
    checks: tuple[AuditCheckResult, ...] = ()
    _exporter: AuditResultExporter | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.feature_count < 0:
            raise ValueError("feature_count must be non-negative")
        if not 0 <= self.quality_score <= 100:
            raise ValueError("quality_score must be between zero and 100")
        names = tuple(check.name for check in self.checks)
        if len(names) != len(set(names)):
            raise ValueError("check names must be unique")
        if not self.metadata.path and self.metadata.feature_count != self.feature_count:
            object.__setattr__(
                self,
                "metadata",
                AuditDatasetMetadata(
                    "",
                    self.dataset_name,
                    "memory",
                    self.crs_guard.crs,
                    self.feature_count,
                    "geometry",
                    0,
                    "in-memory",
                ),
            )

    @property
    def is_clean(self) -> bool:
        return not self.issues

    @property
    def status(self) -> CheckStatus:
        statuses = {check.status for check in self.checks}
        if CheckStatus.ERROR in statuses:
            return CheckStatus.ERROR
        if CheckStatus.FAILED in statuses:
            return CheckStatus.FAILED
        if self.checks and statuses == {CheckStatus.SKIPPED}:
            return CheckStatus.SKIPPED
        return CheckStatus.PASSED if self.passes() else CheckStatus.FAILED

    @property
    def issue_count(self) -> int:
        return len(self.issues) or sum(check.issue_count for check in self.checks)

    @property
    def feature_indices(self) -> tuple[int, ...]:
        indices = {
            index
            for issue in self.issues
            for index in (issue.feature_index, issue.related_feature_index)
            if index is not None
        }
        indices.update(index for check in self.checks for index in check.feature_indices)
        return tuple(sorted(indices))

    def check(self, name: str) -> AuditCheckResult:
        selected = next((check for check in self.checks if check.name == name), None)
        if selected is None:
            raise KeyError(name)
        return selected

    def issues_for_layer(self, kind: IssueGeometryKind | str) -> tuple[DatasetIssue, ...]:
        normalized = IssueGeometryKind(kind)
        return tuple(issue for issue in self.issues if issue.geometry_kind is normalized)

    def passes(self, policy: QualityGatePolicy | None = None) -> bool:
        selected = policy or QualityGatePolicy()
        if self.quality_score < selected.minimum_score:
            return False
        if self.crs_guard.status is CrsUnitStatus.UNKNOWN and not selected.allow_unknown_crs:
            return False
        ranks = {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2, Severity.CRITICAL: 3}
        threshold = ranks[selected.fail_on]
        return not any(ranks[issue.severity] >= threshold for issue in self.issues)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "dataset_name": self.dataset_name,
            "profile_name": self.profile_name,
            "preset": self.preset.value if self.preset else None,
            "feature_count": self.feature_count,
            "quality_score": self.quality_score,
            "is_clean": self.is_clean,
            "crs": {
                "value": self.crs_guard.crs,
                "status": self.crs_guard.status.value,
                "unit_name": self.crs_guard.unit_name,
                "uses_angular_units": self.crs_guard.uses_angular_units,
                "message": self.crs_guard.message,
                "suggested_projected_crs": self.crs_guard.suggested_projected_crs,
            },
            "category_scores": [
                {"category": item.category, "score": item.score, "issue_count": item.issue_count}
                for item in self.category_scores
            ],
            "score_deductions": [
                {
                    "category": item.category,
                    "issue_fingerprint": item.issue_fingerprint,
                    "severity": item.severity.value,
                    "points": item.points,
                    "explanation": item.explanation,
                }
                for item in self.score_deductions
            ],
            "issues": [issue.to_dict() for issue in self.issues],
            "metadata": self.metadata.to_dict(),
            "checks": [check.to_dict() for check in self.checks],
        }

    def to_json(self, destination: str | PathLike[str], *, overwrite: bool = False) -> None:
        self._require_exporter().json(self, Path(destination), overwrite=overwrite)

    def to_html(self, destination: str | PathLike[str], *, overwrite: bool = False) -> None:
        self._require_exporter().html(self, Path(destination), overwrite=overwrite)

    def write_findings(self, destination: str | PathLike[str], *, overwrite: bool = False) -> None:
        self._require_exporter().findings(self, Path(destination), overwrite=overwrite)

    def _require_exporter(self) -> AuditResultExporter:
        if self._exporter is None:
            raise RuntimeError(
                "Exports require a file audit result returned by geoqc.audit_dataset()."
            )
        return self._exporter


@dataclass(frozen=True, slots=True)
class WorkflowArtifacts:
    result: DatasetAuditResult
    issue_dataset: str | None = None
    report: str | None = None
