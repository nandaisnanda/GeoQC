from geoqc.domain.models import GeographicPoint, QualityReport, QualityReportIssue
from geoqc.domain.rules import Severity
from geoqc.infrastructure.reporting import InteractiveMapRenderer


def _issue(
    code: str,
    severity: Severity,
    latitude: float | None,
    longitude: float | None,
) -> QualityReportIssue:
    map_location = (
        GeographicPoint(latitude=latitude, longitude=longitude)
        if latitude is not None and longitude is not None
        else None
    )
    return QualityReportIssue(
        code=code,
        title="Unsafe <script>alert('x')</script> geometry",
        description="The polygon crosses itself.",
        severity=severity,
        category="Geometry",
        recommendation="Repair topology.",
        location="Feature 42",
        map_location=map_location,
    )


def test_render_returns_none_when_report_has_no_geolocated_issues() -> None:
    report = QualityReport(
        title="QC",
        dataset_name="roads.gpkg",
        total_checks=1,
        passed_checks=0,
        issues=(_issue("GEO-001", Severity.ERROR, None, None),),
    )

    assert InteractiveMapRenderer().render(report) is None


def test_render_builds_markers_popups_fit_bounds_and_focus_api() -> None:
    report = QualityReport(
        title="QC",
        dataset_name="parcels.gpkg",
        total_checks=2,
        passed_checks=0,
        issues=(
            _issue("GEO-001", Severity.ERROR, -6.1754, 106.8272),
            _issue("GEO-002", Severity.CRITICAL, -6.2, 106.8167),
        ),
    )

    html = InteractiveMapRenderer().render(report)

    assert html is not None
    assert "leaflet" in html.lower()
    assert "basemaps.cartocdn.com/light_all" in html
    assert "#dc2626" in html
    assert "#881337" in html
    assert "fitBounds" in html
    assert "window.GeoQCMap" in html
    assert "focusIssue" in html
    assert "flyTo" in html
    assert '"issue-0"' in html
    assert "Unsafe &lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt; geometry" in html
    assert "Unsafe <script>" not in html
