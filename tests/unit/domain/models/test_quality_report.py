import pytest

from geoqc.domain.models import (
    GeographicPoint,
    QualityBadge,
    QualityReport,
    QualityReportIssue,
)
from geoqc.domain.rules import Severity


def _issue(
    severity: Severity = Severity.ERROR,
    recommendation: str = "Repair the feature.",
) -> QualityReportIssue:
    return QualityReportIssue(
        code="GEO-001",
        title="Invalid geometry",
        description="The polygon intersects itself.",
        severity=severity,
        category="Geometry",
        recommendation=recommendation,
        location="Feature 42",
    )


def test_report_calculates_score_statistics_and_unique_recommendations() -> None:
    report = QualityReport(
        title="Dataset quality",
        dataset_name="roads.gpkg",
        total_checks=4,
        passed_checks=3,
        issues=(
            _issue(Severity.ERROR),
            _issue(Severity.WARNING),
            _issue(Severity.INFO, "Review the source metadata."),
        ),
    )

    assert report.quality_score == 84.0
    assert report.quality_badge is QualityBadge.GOOD
    assert report.failed_checks == 1
    assert report.issue_count(Severity.ERROR) == 1
    assert report.issue_count("warning") == 1
    assert report.recommendations == (
        "Repair the feature.",
        "Review the source metadata.",
    )
    assert report.summary_text == ("3 of 4 quality checks passed; 3 issue(s) require attention.")


def test_empty_check_run_has_perfect_score_and_custom_summary() -> None:
    report = QualityReport(
        title="Dataset quality",
        dataset_name="empty.gpkg",
        total_checks=0,
        passed_checks=0,
        summary="No checks were selected.",
    )

    assert report.quality_score == 100.0
    assert report.quality_badge is QualityBadge.EXCELLENT
    assert report.summary_text == "No checks were selected."


@pytest.mark.parametrize(
    ("severity", "expected_score"),
    [
        (Severity.INFO, 99.0),
        (Severity.WARNING, 95.0),
        (Severity.ERROR, 90.0),
        (Severity.CRITICAL, 75.0),
    ],
)
def test_quality_score_uses_severity_penalties(severity: Severity, expected_score: float) -> None:
    report = QualityReport(
        title="Dataset quality",
        dataset_name="roads.gpkg",
        total_checks=1,
        passed_checks=0,
        issues=(_issue(severity),),
    )

    assert report.quality_score == expected_score


@pytest.mark.parametrize(
    ("issue_count", "expected_score", "expected_badge"),
    [
        (10, 90.0, QualityBadge.EXCELLENT),
        (11, 89.0, QualityBadge.GOOD),
        (25, 75.0, QualityBadge.GOOD),
        (26, 74.0, QualityBadge.FAIR),
        (50, 50.0, QualityBadge.FAIR),
        (51, 49.0, QualityBadge.POOR),
        (101, 0.0, QualityBadge.POOR),
    ],
)
def test_quality_badge_boundaries_and_zero_clamp(
    issue_count: int,
    expected_score: float,
    expected_badge: QualityBadge,
) -> None:
    report = QualityReport(
        title="Dataset quality",
        dataset_name="roads.gpkg",
        total_checks=issue_count,
        passed_checks=0,
        issues=tuple(_issue(Severity.INFO) for _ in range(issue_count)),
    )

    assert report.quality_score == expected_score
    assert report.quality_badge is expected_badge


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"title": " "}, "title must not be empty"),
        ({"dataset_name": ""}, "dataset_name must not be empty"),
        ({"total_checks": -1, "passed_checks": 0}, "total_checks must not be negative"),
        ({"passed_checks": 3}, "passed_checks must be between zero and total_checks"),
        ({"summary": " "}, "summary must not be empty when provided"),
    ],
)
def test_report_rejects_invalid_values(changes: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "title": "Dataset quality",
        "dataset_name": "roads.gpkg",
        "total_checks": 2,
        "passed_checks": 1,
    }
    values.update(changes)

    with pytest.raises(ValueError, match=message):
        QualityReport(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field_name",
    ["code", "title", "description", "category", "recommendation"],
)
def test_issue_rejects_empty_required_text(field_name: str) -> None:
    values: dict[str, object] = {
        "code": "GEO-001",
        "title": "Invalid geometry",
        "description": "The polygon intersects itself.",
        "severity": Severity.ERROR,
        "category": "Geometry",
        "recommendation": "Repair the feature.",
    }
    values[field_name] = " "

    with pytest.raises(ValueError, match=field_name):
        QualityReportIssue(**values)  # type: ignore[arg-type]


def test_issue_rejects_empty_location() -> None:
    with pytest.raises(ValueError, match="location must not be empty"):
        QualityReportIssue(
            code="GEO-001",
            title="Invalid geometry",
            description="The polygon intersects itself.",
            severity=Severity.ERROR,
            category="Geometry",
            recommendation="Repair the feature.",
            location=" ",
        )


@pytest.mark.parametrize(
    ("latitude", "longitude", "message"),
    [
        (91.0, 0.0, "latitude must be between"),
        (0.0, -181.0, "longitude must be between"),
        (float("inf"), 0.0, "finite numbers"),
    ],
)
def test_geographic_point_rejects_invalid_wgs84_coordinates(
    latitude: float,
    longitude: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        GeographicPoint(latitude=latitude, longitude=longitude)
