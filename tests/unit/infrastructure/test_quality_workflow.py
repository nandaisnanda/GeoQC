"""Tests for the plugin-ready dataset quality workflow."""

import pytest
from shapely import box, from_wkt
from shapely.geometry import LineString, MultiLineString, Point, Polygon

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


def test_boundary_must_match_reports_only_unmatched_boundary() -> None:
    layers = (
        geoqc.DatasetLayer("source", (box(0, 0, 1, 1).wkt,)),
        geoqc.DatasetLayer("reference", (box(0, 0, 2, 1).wkt,)),
    )
    rule = geoqc.TopologyRule(
        geoqc.TopologyRuleType.BOUNDARY_MUST_MATCH,
        "source",
        "reference",
    )

    issues = geoqc.evaluate_topology_rules(layers, (rule,))

    assert len(issues) == 1
    assert issues[0].metadata["unmatched_length"] == pytest.approx(1.0)
    assert from_wkt(issues[0].geometry_wkt).geom_type == "LineString"


def test_line_endpoint_rules_distinguish_endpoint_and_line_connections() -> None:
    layers = (
        geoqc.DatasetLayer(
            "roads",
            (
                LineString([(0, 0), (1, 0)]).wkt,
                LineString([(1, -1), (1, 1)]).wkt,
            ),
        ),
    )
    rules = (
        geoqc.TopologyRule(geoqc.TopologyRuleType.NO_DANGLES, "roads"),
        geoqc.TopologyRule(geoqc.TopologyRuleType.ENDPOINT_MUST_CONNECT, "roads"),
    )

    issues = geoqc.evaluate_topology_rules(layers, rules)

    assert any(
        item.issue_type == "no_dangles" and from_wkt(item.geometry_wkt).equals(Point(1, 0))
        for item in issues
    )
    assert not any(
        item.issue_type == "endpoint_must_connect"
        and from_wkt(item.geometry_wkt).equals(Point(1, 0))
        for item in issues
    )


def test_detects_line_overshoot_and_undershoot() -> None:
    layers = (
        geoqc.DatasetLayer(
            "roads",
            (
                LineString([(0, 0), (1.1, 0)]).wkt,
                LineString([(1, -1), (1, 1)]).wkt,
                LineString([(2, 0), (2.9, 0)]).wkt,
                LineString([(3, -1), (3, 1)]).wkt,
            ),
        ),
    )
    rule = geoqc.TopologyRule(
        geoqc.TopologyRuleType.NO_OVERSHOOT_UNDERSHOOT, "roads", tolerance=0.2
    )

    issues = geoqc.evaluate_topology_rules(layers, (rule,))

    assert {item.metadata["subtype"] for item in issues} == {"overshoot", "undershoot"}


def test_geometry_type_and_singlepart_rules() -> None:
    layers = (
        geoqc.DatasetLayer(
            "mixed",
            (Point(0, 0).wkt, MultiLineString([[(0, 0), (1, 0)], [(2, 0), (3, 0)]]).wkt),
        ),
    )
    rules = (
        geoqc.TopologyRule(
            geoqc.TopologyRuleType.ALLOWED_GEOMETRY_TYPE,
            "mixed",
            allowed_geometry_types=("Point",),
        ),
        geoqc.TopologyRule(geoqc.TopologyRuleType.SINGLEPART_ONLY, "mixed"),
    )

    issues = geoqc.evaluate_topology_rules(layers, rules)

    assert {item.issue_type for item in issues} == {"allowed_geometry_type", "singlepart_only"}


def test_spike_and_minimum_vertex_metrics_are_reported() -> None:
    polygon = Polygon([(0, 0), (2, 0), (1, 0.01), (2, 2), (0, 2)])
    layers = (geoqc.DatasetLayer("parcels", (polygon.wkt,)),)
    rules = (
        geoqc.TopologyRule(geoqc.TopologyRuleType.NO_SPIKES, "parcels", minimum_angle=5),
        geoqc.TopologyRule(
            geoqc.TopologyRuleType.MINIMUM_VERTEX_DISTANCE,
            "parcels",
            minimum_distance=1.5,
        ),
    )

    issues = geoqc.evaluate_topology_rules(layers, rules)

    assert any(item.issue_type == "no_spikes" for item in issues)
    assert any(item.issue_type == "minimum_vertex_distance" for item in issues)


def test_minimum_segment_length_reports_zero_and_short_segments() -> None:
    layers = (geoqc.DatasetLayer("lines", (LineString([(0, 0), (0.01, 0), (1, 0)]).wkt,)),)
    rule = geoqc.TopologyRule(
        geoqc.TopologyRuleType.MINIMUM_SEGMENT_LENGTH,
        "lines",
        minimum_length=0.1,
    )

    issues = geoqc.evaluate_topology_rules(layers, (rule,))

    assert len(issues) == 1
    assert issues[0].metadata["segment_length"] == pytest.approx(0.01)


@pytest.mark.parametrize(
    ("rule_type", "source", "reference", "expected"),
    [
        (geoqc.TopologyRuleType.MUST_TOUCH, box(0, 0, 1, 1), box(1, 0, 2, 1), 0),
        (geoqc.TopologyRuleType.MUST_INTERSECT, Point(5, 5), box(0, 0, 1, 1), 1),
        (geoqc.TopologyRuleType.MUST_COVER, box(0, 0, 3, 3), box(1, 1, 2, 2), 0),
    ],
)
def test_touch_intersect_and_cover_relations(
    rule_type: geoqc.TopologyRuleType,
    source: object,
    reference: object,
    expected: int,
) -> None:
    assert hasattr(source, "wkt") and hasattr(reference, "wkt")
    layers = (
        geoqc.DatasetLayer("source", (source.wkt,)),
        geoqc.DatasetLayer("reference", (reference.wkt,)),
    )
    rule = geoqc.TopologyRule(rule_type, "source", "reference")

    assert len(geoqc.evaluate_topology_rules(layers, (rule,))) == expected


def test_attribute_driven_overlap_policy_uses_layer_attributes() -> None:
    layers = (
        geoqc.DatasetLayer(
            "zones",
            (box(0, 0, 2, 2).wkt, box(1, 0, 3, 2).wkt, box(2, 0, 4, 2).wkt),
            attributes=(({"class": "A"}), ({"class": "A"}), ({"class": "B"})),
        ),
    )
    rule = geoqc.TopologyRule(
        geoqc.TopologyRuleType.ATTRIBUTE_OVERLAP,
        "zones",
        attribute_column="class",
        overlap_policy=geoqc.AttributeOverlapPolicy.ALLOW_EQUAL,
    )

    issues = geoqc.evaluate_topology_rules(layers, (rule,))

    assert len(issues) == 1
    assert issues[0].metadata["source_value"] == "A"
    assert issues[0].metadata["related_value"] == "B"


def test_precision_grid_reports_off_grid_vertices_with_tolerance() -> None:
    layers = (geoqc.DatasetLayer("survey", (LineString([(0, 0), (1.01, 1)]).wkt,)),)
    rule = geoqc.TopologyRule(
        geoqc.TopologyRuleType.PRECISION_GRID,
        "survey",
        precision_grid_size=0.1,
        tolerance=0.001,
    )

    issues = geoqc.evaluate_topology_rules(layers, (rule,))

    assert len(issues) == 1
    assert issues[0].metadata["off_grid_vertices"] == 1


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
