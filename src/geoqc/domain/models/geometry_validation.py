"""Framework-independent results produced by geometry validation adapters."""

from dataclasses import dataclass
from enum import StrEnum


class GeometryIssueType(StrEnum):
    """Stable categories of geometry quality problems."""

    INVALID_GEOMETRY = "invalid_geometry"
    EMPTY_GEOMETRY = "empty_geometry"
    SELF_INTERSECTION = "self_intersection"
    RING_ERROR = "ring_error"
    DUPLICATE_VERTEX = "duplicate_vertex"


@dataclass(frozen=True, slots=True)
class GeometryValidationIssue:
    """One detected geometry problem with a diagnostic message."""

    issue_type: GeometryIssueType
    message: str


@dataclass(frozen=True, slots=True)
class GeometryValidationResult:
    """Complete validation outcome for one geometry."""

    geometry_type: str
    issues: tuple[GeometryValidationIssue, ...]

    @property
    def is_valid(self) -> bool:
        """Return whether no quality problems were detected."""
        return not self.issues

    def has_issue(self, issue_type: GeometryIssueType) -> bool:
        """Return whether the result contains a particular issue category."""
        return any(issue.issue_type is issue_type for issue in self.issues)
