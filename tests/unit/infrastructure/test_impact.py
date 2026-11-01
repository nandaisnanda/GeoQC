"""Impact summary: affected area and length in metric units."""

import json
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import pytest
from shapely.geometry import LineString, Point, box
from typer.testing import CliRunner, Result

from geoqc import build_quality_report
from geoqc.domain.models.topology import DatasetIssue, IssueGeometryKind, RepairRisk
from geoqc.domain.rules import Severity
from geoqc.infrastructure.gis.impact import IMPACT_SKIPPED_MESSAGE, compute_impact
from geoqc.infrastructure.reporting import HtmlReportRenderer
from geoqc.interfaces.cli.main import app


def _issue(
    code: str,
    geometry: str,
    kind: IssueGeometryKind,
    feature_index: int,
    severity: Severity = Severity.ERROR,
) -> DatasetIssue:
    return DatasetIssue(
        code=code,
        issue_type=code.lower(),
        title=code,
        message=code,
        severity=severity,
        category="topology",
        recommendation="Review.",
        repair_risk=RepairRisk.REVIEW,
        geometry_kind=kind,
        geometry_wkt=geometry,
        layer="layer",
        feature_index=feature_index,
    )


def _check(*args: str) -> Result:
    with pytest.warns(DeprecationWarning):
        return CliRunner().invoke(app, ["check", *args])


def test_overlap_of_one_hectare_is_reported_in_json_and_cli(tmp_path: Path) -> None:
    # Two 2 ha parcels in UTM 49S sharing a 100 m x 100 m strip.
    source = tmp_path / "parcels.gpkg"
    gpd.GeoDataFrame(
        geometry=[
            box(430_000, 9_120_000, 430_200, 9_120_100),
            box(430_100, 9_120_000, 430_300, 9_120_100),
        ],
        crs="EPSG:32749",
    ).to_file(source)
    report = tmp_path / "report.json"

    result = _check(str(source), "--no-output", "--report", str(report))

    payload = json.loads(report.read_text(encoding="utf-8"))
    layer = payload["impact"]["layers"][0]
    overlap = next(code for code in layer["codes"] if code["code"] == "TOP-NO-OVERLAP")
    assert overlap["unit"] == "ha"
    assert overlap["measure"] == pytest.approx(1.0, abs=0.01)
    assert overlap["feature_count"] == 2
    assert layer["affected_measure"] == pytest.approx(4.0, abs=0.01)
    assert {"issues", "crs", "quality_score"} <= payload.keys()
    assert "Impact: 4.00 ha of 4.00 ha (100.0%) sits in features with errors" in result.stdout


def test_road_length_is_reported_in_kilometres() -> None:
    road = LineString([(430_000, 9_120_000), (432_500, 9_120_000)])
    frame = gpd.GeoDataFrame(
        geometry=[road, LineString([(430_000, 9_121_000), (437_500, 9_121_000)])],
        crs="EPSG:32749",
    )
    issue = _issue("TOP-SINGLEPART-ONLY", road.wkt, IssueGeometryKind.LINE, 0)

    impact = compute_impact([issue], frame, "roads")

    layer = impact.layers[0]
    assert layer.codes[0].measure == pytest.approx(2.5)
    assert layer.codes[0].unit == "km"
    assert layer.affected_measure == pytest.approx(2.5)
    assert layer.total_measure == pytest.approx(10.0)
    assert impact.cli_lines()[0] == (
        "Impact: 2.50 km of 10.00 km (25.0%) sits in features with errors"
    )


def test_feature_with_three_issues_is_counted_once() -> None:
    parcel = box(430_000, 9_120_000, 430_100, 9_120_100)
    frame = gpd.GeoDataFrame(
        geometry=[parcel, box(430_200, 9_120_000, 430_300, 9_120_100)], crs="EPSG:32749"
    )
    point = "POINT (430050 9120050)"
    issues = [
        _issue("GEO-SELF_INTERSECTION", point, IssueGeometryKind.POINT, 0),
        _issue("TOP-NO-GAPS", parcel.wkt, IssueGeometryKind.POLYGON, 0),
        _issue("TOP-NO-GAPS", parcel.wkt, IssueGeometryKind.POLYGON, 0),
    ]

    layer = compute_impact(issues, frame, "parcels").layers[0]

    assert layer.affected_feature_count == 1
    assert layer.affected_measure == pytest.approx(1.0)
    assert layer.share_percent == pytest.approx(50.0)
    gaps = next(code for code in layer.codes if code.code == "TOP-NO-GAPS")
    assert (gaps.issue_count, gaps.feature_count) == (2, 1)
    assert gaps.measure == pytest.approx(2.0)
    point_code = next(code for code in layer.codes if code.unit == "count")
    assert point_code.measure is None


def test_info_findings_are_excluded() -> None:
    road = LineString([(430_000, 9_120_000), (431_000, 9_120_000)])
    frame = gpd.GeoDataFrame(geometry=[road], crs="EPSG:32749")
    issue = _issue(
        "TOP-NO-DANGLES", "POINT (430000 9120000)", IssueGeometryKind.POINT, 0, Severity.INFO
    )

    layer = compute_impact([issue], frame, "roads").layers[0]

    assert layer.codes == ()
    assert layer.affected_feature_count == 0


def test_missing_crs_skips_impact() -> None:
    frame = gpd.GeoDataFrame(geometry=[box(0, 0, 100, 100)])
    issue = _issue("TOP-NO-GAPS", box(0, 0, 100, 100).wkt, IssueGeometryKind.POLYGON, 0)

    impact = compute_impact([issue], frame, "parcels")

    assert impact.skipped
    assert impact.layers == ()
    assert impact.cli_lines() == [IMPACT_SKIPPED_MESSAGE]
    assert IMPACT_SKIPPED_MESSAGE == "Impact: skipped (CRS missing)"


def test_geographic_crs_is_measured_in_estimated_utm_with_note() -> None:
    # About 1.1 km of road running north near Yogyakarta.
    road = LineString([(110.37, -7.80), (110.37, -7.79)])
    frame = gpd.GeoDataFrame(geometry=[road], crs="EPSG:4326")
    issue = _issue("TOP-SINGLEPART-ONLY", road.wkt, IssueGeometryKind.LINE, 0)

    impact = compute_impact([issue], frame, "roads")

    assert impact.metric_crs == "EPSG:32749"
    assert impact.note is not None and "UTM" in impact.note
    assert sum(line.startswith("  Note:") for line in impact.cli_lines()) == 1
    assert impact.layers[0].codes[0].measure == pytest.approx(1.106, abs=0.01)


def test_html_report_has_impact_section(tmp_path: Path) -> None:
    from geoqc import audit_dataset

    source = tmp_path / "parcels.gpkg"
    frame = gpd.GeoDataFrame(
        geometry=[
            box(430_000, 9_120_000, 430_200, 9_120_100),
            box(430_100, 9_120_000, 430_300, 9_120_100),
        ],
        crs="EPSG:32749",
    )
    frame.to_file(source)
    result = audit_dataset(source)
    impact = compute_impact(result.issues, frame, "parcels")

    html = HtmlReportRenderer().render(build_quality_report(result), impact=impact.to_dict())
    plain = HtmlReportRenderer().render(build_quality_report(result))

    assert 'id="impact-heading">Impact</h2>' in html
    assert "<h3>parcels</h3>" in html
    assert "impact-heading" not in plain


def test_point_layer_reports_feature_share_only() -> None:
    frame = gpd.GeoDataFrame(
        geometry=[Point(430_000, 9_120_000), Point(430_050, 9_120_000)], crs="EPSG:32749"
    )
    issue = _issue("GEO-DUPLICATE", "POINT (430000 9120000)", IssueGeometryKind.POINT, 0)

    impact = compute_impact([issue], frame, "wells")

    layer = impact.layers[0]
    assert layer.unit == "count"
    assert layer.total_measure is None
    assert impact.cli_lines()[0] == "Impact: 1 of 2 features (50.0%) have errors"


def test_cli_without_crs_prints_skip_line(tmp_path: Path) -> None:
    source = tmp_path / "parcels.gpkg"
    gpd.GeoDataFrame(geometry=[box(0, 0, 200, 100), box(100, 0, 300, 100)]).to_file(source)

    result = _check(str(source), "--no-output")

    assert "Impact: skipped (CRS missing)" in result.stdout
    assert "Impact: " not in result.stdout.replace("Impact: skipped (CRS missing)", "")


def test_cli_multi_layer_prints_impact_per_layer(tmp_path: Path) -> None:
    source = tmp_path / "blocks.gpkg"
    for name, offset in (("north", 0), ("south", 1_000)):
        gpd.GeoDataFrame(
            geometry=[
                box(430_000, 9_120_000 + offset, 430_200, 9_120_100 + offset),
                box(430_100, 9_120_000 + offset, 430_300, 9_120_100 + offset),
            ],
            crs="EPSG:32749",
        ).to_file(source, layer=name)

    result = _check(str(source), "--no-output")

    lines = result.stdout.splitlines()
    impacts = [line for line in lines if line.startswith("Impact: ")]
    assert impacts == ["Impact: 4.00 ha of 4.00 ha (100.0%) sits in features with errors"] * 2
    assert lines.index("Layer: north") < lines.index(impacts[0]) < lines.index("Layer: south")


def test_html_report_shows_skip_when_crs_missing(tmp_path: Path) -> None:
    from geoqc import audit_dataset

    source = tmp_path / "parcels.gpkg"
    frame = gpd.GeoDataFrame(geometry=[box(0, 0, 200, 100), box(100, 0, 300, 100)])
    frame.to_file(source)
    result = audit_dataset(source)
    impact = compute_impact(result.issues, frame, "parcels")

    html = HtmlReportRenderer().render(build_quality_report(result), impact=impact.to_dict())

    assert 'id="impact-heading">Impact</h2>' in html
    assert "Impact: skipped (CRS missing)" in html
    assert "impact-table" not in html.split("</style>", 1)[1]
