"""Unit tests for framework-independent geometry validation results."""

from geoqc.domain.models import (
    GeometryIssueType,
    GeometryValidationIssue,
    GeometryValidationResult,
)


def test_geometry_validation_result_exposes_issue_queries() -> None:
    """Consumers can inspect overall validity and stable issue categories."""
    issue = GeometryValidationIssue(
        GeometryIssueType.DUPLICATE_VERTEX,
        "Duplicate vertex detected.",
    )

    result = GeometryValidationResult("LineString", (issue,))

    assert not result.is_valid
    assert result.has_issue(GeometryIssueType.DUPLICATE_VERTEX)
    assert not result.has_issue(GeometryIssueType.EMPTY_GEOMETRY)


def test_geometry_validation_result_without_issues_is_valid() -> None:
    """An empty finding collection represents a valid geometry."""
    result = GeometryValidationResult("Polygon", ())

    assert result.is_valid
