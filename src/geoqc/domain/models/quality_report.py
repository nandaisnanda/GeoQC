"""Framework-independent data used to build quality reports."""

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from geoqc.domain.rules.models import Severity


class QualityBadge(StrEnum):
    """Human-readable quality classification derived from a quality score."""

    EXCELLENT = "Excellent"
    GOOD = "Good"
    FAIR = "Fair"
    POOR = "Poor"


SEVERITY_PENALTIES: dict[Severity, int] = {
    Severity.INFO: 1,
    Severity.WARNING: 5,
    Severity.ERROR: 10,
    Severity.CRITICAL: 25,
}


@dataclass(frozen=True, slots=True)
class GeographicPoint:
    """A WGS84 point suitable for placing an issue on an interactive map."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not isfinite(self.latitude) or not isfinite(self.longitude):
            raise ValueError("map coordinates must be finite numbers")
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")


@dataclass(frozen=True, slots=True)
class QualityReportIssue:
    """One normalized, actionable issue displayed in a quality report."""

    code: str
    title: str
    description: str
    severity: Severity
    category: str
    recommendation: str
    location: str | None = None
    map_location: GeographicPoint | None = None

    def __post_init__(self) -> None:
        for field_name in ("code", "title", "description", "category", "recommendation"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.location is not None and not self.location.strip():
            raise ValueError("location must not be empty when provided")


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Aggregate quality information independent from its output format."""

    title: str
    dataset_name: str
    total_checks: int
    passed_checks: int
    issues: tuple[QualityReportIssue, ...] = ()
    summary: str | None = None

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("title must not be empty")
        if not self.dataset_name.strip():
            raise ValueError("dataset_name must not be empty")
        if self.total_checks < 0:
            raise ValueError("total_checks must not be negative")
        if not 0 <= self.passed_checks <= self.total_checks:
            raise ValueError("passed_checks must be between zero and total_checks")
        if self.summary is not None and not self.summary.strip():
            raise ValueError("summary must not be empty when provided")

    @property
    def failed_checks(self) -> int:
        """Return checks that did not pass."""
        return self.total_checks - self.passed_checks

    @property
    def quality_score(self) -> float:
        """Return 0-100 after subtracting the penalty for each issue severity."""
        total_penalty = sum(SEVERITY_PENALTIES[issue.severity] for issue in self.issues)
        return float(max(0, 100 - total_penalty))

    @property
    def quality_badge(self) -> QualityBadge:
        """Classify the quality score using stable, inclusive lower boundaries."""
        if self.quality_score >= 90:
            return QualityBadge.EXCELLENT
        if self.quality_score >= 75:
            return QualityBadge.GOOD
        if self.quality_score >= 50:
            return QualityBadge.FAIR
        return QualityBadge.POOR

    @property
    def summary_text(self) -> str:
        """Return a supplied summary or a deterministic default summary."""
        if self.summary is not None:
            return self.summary
        return (
            f"{self.passed_checks} of {self.total_checks} quality checks passed; "
            f"{len(self.issues)} issue(s) require attention."
        )

    def issue_count(self, severity: Severity | str) -> int:
        """Count report issues for one severity."""
        normalized_severity = Severity(severity)
        return sum(issue.severity is normalized_severity for issue in self.issues)

    @property
    def recommendations(self) -> tuple[str, ...]:
        """Return recommendations once each, preserving issue order."""
        return tuple(dict.fromkeys(issue.recommendation for issue in self.issues))
