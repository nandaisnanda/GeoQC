from pathlib import Path

from geoqc.domain.models import GeographicPoint, QualityReport, QualityReportIssue
from geoqc.domain.rules import Severity
from geoqc.infrastructure.reporting import HtmlReportRenderer


def _report() -> QualityReport:
    return QualityReport(
        title="Municipal Parcels QC",
        dataset_name="parcels <2026>.gpkg",
        total_checks=5,
        passed_checks=3,
        summary="Geometry and attribute checks completed.",
        issues=(
            QualityReportIssue(
                code="GEO-001",
                title="Self intersection",
                description="Polygon <script>alert('x')</script> crosses itself.",
                severity=Severity.CRITICAL,
                category="Geometry",
                recommendation="Repair polygon topology.",
                location="Feature 17",
                map_location=GeographicPoint(latitude=-6.1754, longitude=106.8272),
            ),
            QualityReportIssue(
                code="ATTR-002",
                title="Missing owner",
                description="A required owner value is null.",
                severity=Severity.WARNING,
                category="Attribute",
                recommendation="Populate owner from the source register.",
            ),
        ),
    )


def test_render_contains_all_required_report_sections_and_values() -> None:
    html = HtmlReportRenderer().render(_report())

    assert "Municipal Parcels QC" in html
    assert "Quality Score" in html
    assert "70.0%" in html
    assert 'class="quality-badge fair">Fair</span>' in html
    assert "Summary" in html
    assert "Statistics" in html
    assert "Error List" in html
    assert "Recommendations" in html
    assert "Self intersection" in html
    assert 'class="badge critical"' in html
    assert "<strong>1</strong> Warning" in html
    assert "<strong>1</strong> Critical" in html
    assert "Feature 17" in html
    assert "Interactive Error Map" in html
    assert 'id="geoqc-map"' in html
    assert 'data-map-issue="issue-0"' in html
    assert "api.focusIssue(button.dataset.mapIssue)" in html


def test_render_autoescapes_user_controlled_content_and_is_responsive() -> None:
    html = HtmlReportRenderer().render(_report())

    assert "parcels &lt;2026&gt;.gpkg" in html
    assert "&lt;script&gt;alert" in html
    assert "<script>alert" not in html
    assert '<meta name="viewport"' in html
    assert "@media (max-width: 760px)" in html
    assert "@media print" in html


def test_render_without_issues_shows_successful_empty_states() -> None:
    report = QualityReport(
        title="Roads QC",
        dataset_name="roads.gpkg",
        total_checks=3,
        passed_checks=3,
    )

    html = HtmlReportRenderer().render(report)

    assert "100.0%" in html
    assert 'class="quality-badge excellent">Excellent</span>' in html
    assert "No quality errors were detected." in html
    assert "No corrective action is required." in html
    assert "Interactive Error Map" not in html


def test_write_creates_parent_directories_and_utf8_file(tmp_path: Path) -> None:
    destination = tmp_path / "reports" / "quality.html"

    result = HtmlReportRenderer().write(_report(), destination)

    assert result == destination
    assert destination.is_file()
    assert "GeoQC quality report" in destination.read_text(encoding="utf-8")
