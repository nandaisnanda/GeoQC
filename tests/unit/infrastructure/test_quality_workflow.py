"""Tests for the plugin-ready dataset quality workflow."""

import pytest
from shapely import box, from_wkt
from shapely.geometry import LineString, Point, Polygon

import geoqc
from geoqc.domain.rules import Severity


def test_parcel_preset_returns_issue_geometry_scores_and_ci_decision() -> None:
    result = geoqc.audit_geometries(
        [box(0, 0, 2, 2), box(1, 0, 3, 2)],
        dataset_name="parcels",
        preset="parcel",
        crs="EPSG:32748",
    )

    overlap = next(issue for issue in result.issues if issue.issue_type == "overlap")
    assert overlap.repair_risk is geoqc.RepairRisk.DANGEROUS
    assert from_wkt(overlap.geometry_wkt).area == 2.0
    assert result.crs_guard.status is geoqc.CrsUnitStatus.SAFE
    assert result.issues_for_layer("polygon")
    assert not result.passes()
    assert result.to_dict()["dataset_name"] == "parcels"


def test_point_survey_preset_detects_duplicate_points() -> None:
    result = geoqc.audit_geometries(
        [Point(1, 2), Point(1, 2), Point(3, 4)],
        preset=geoqc.QualityPreset.POINT_SURVEY,
        crs="EPSG:4326",
    )

    assert any(issue.issue_type == "duplicate_feature" for issue in result.issues)
    assert result.crs_guard.uses_angular_units
    assert result.crs_guard.suggested_projected_crs == "EPSG:32631"


def test_road_preset_exposes_point_findings() -> None:
    result = geoqc.audit_geometries(
        [LineString([(0, 0), (1, 0)]), LineString([(1.05, 0), (2, 0)])],
        preset="road",
        crs="EPSG:3857",
        tolerance=0.1,
    )

    assert any(issue.issue_type == "broken_connection" for issue in result.issues)
    assert result.issues_for_layer(geoqc.IssueGeometryKind.POINT)


def test_custom_cross_layer_rules_find_outside_and_forbidden_intersection() -> None:
    layers = (
        geoqc.DatasetLayer("buildings", (box(1, 1, 2, 2).wkt, box(20, 20, 21, 21).wkt)),
        geoqc.DatasetLayer("parcels", (box(0, 0, 10, 10).wkt,)),
        geoqc.DatasetLayer("rivers", (LineString([(0, 1.5), (3, 1.5)]).wkt,)),
    )
    rules = (
        geoqc.TopologyRule(geoqc.TopologyRuleType.MUST_BE_INSIDE, "buildings", "parcels"),
        geoqc.TopologyRule(geoqc.TopologyRuleType.MUST_NOT_INTERSECT, "buildings", "rivers"),
    )

    issues = geoqc.evaluate_topology_rules(layers, rules)

    assert {item.issue_type for item in issues} == {"must_be_inside", "must_not_intersect"}


def test_safe_repair_only_removes_duplicate_vertices() -> None:
    duplicated = Polygon([(0, 0), (0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
    bowtie = Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])

    result = geoqc.repair_geometries_safely([duplicated, bowtie])

    assert result.report.results[0].result.has_action(geoqc.RepairIssueType.DUPLICATE_VERTEX)
    assert result.report.results[1].result.before_wkt == result.report.results[1].result.after_wkt


def test_audit_converts_to_existing_html_report_model() -> None:
    audit = geoqc.audit_geometries([Point()], dataset_name="survey")

    report = geoqc.build_quality_report(audit)

    assert report.dataset_name == "survey"
    assert report.issues[0].code == "GEO-EMPTY_GEOMETRY"
    assert "Quality score" in report.summary_text


def test_issue_layer_adapter_returns_qgis_ready_geodataframe() -> None:
    audit = geoqc.audit_geometries(
        [box(0, 0, 2, 2), box(1, 0, 3, 2)], preset="parcel", crs="EPSG:3857"
    )

    layer = geoqc.issues_to_geodataframe(audit, "polygon")

    assert layer.crs is not None
    assert "repair_risk" in layer.columns
    assert "overlap" in set(layer["issue_type"])


def test_quality_gate_can_be_tuned_for_warnings_and_unknown_crs() -> None:
    clean = geoqc.audit_geometries([Point(1, 2)])
    policy = geoqc.QualityGatePolicy(
        minimum_score=100, fail_on=Severity.CRITICAL, allow_unknown_crs=True
    )

    assert clean.passes(policy)


@pytest.mark.parametrize("value", [object(), "POINT (1 2)"])
def test_audit_rejects_non_geometry(value: object) -> None:
    with pytest.raises(TypeError):
        geoqc.audit_geometries([value])  # type: ignore[list-item]
