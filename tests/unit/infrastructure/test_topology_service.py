"""Rule selection and input validation in evaluate_topology_rules."""

import pytest
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from geoqc.domain.models import DatasetIssue, DatasetLayer, TopologyRule, TopologyRuleType
from geoqc.domain.rules import Severity
from geoqc.infrastructure.gis.topology_service import evaluate_topology_rules

CRS = "EPSG:32749"


def _layer(name: str, *geometries: BaseGeometry) -> DatasetLayer:
    return DatasetLayer(name, tuple(g.wkt for g in geometries), crs=CRS)


PARCELS = _layer("parcels", box(0, 0, 10, 10), box(5, 5, 15, 15), box(5, 5, 15, 15))
RING = _layer("ring", box(0, 0, 3, 1), box(0, 2, 3, 3), box(0, 1, 1, 2), box(2, 1, 3, 2))
SMALL = _layer("small", box(0, 0, 0.1, 0.1), box(5, 5, 9, 9))
AREA = _layer("area", box(0, 0, 12, 12))
FAR = _layer("far", box(100, 100, 110, 110))


def _codes(issues: tuple[DatasetIssue, ...]) -> list[tuple[str, int | None]]:
    return [(issue.code, issue.feature_index) for issue in issues]


def test_no_overlap_reports_each_overlapping_pair() -> None:
    issues = evaluate_topology_rules(
        [PARCELS], [TopologyRule(TopologyRuleType.NO_OVERLAP, "parcels")]
    )

    assert {issue.code for issue in issues} == {"TOP-NO-OVERLAP"}
    assert len(issues) == 3
    assert all(issue.severity is Severity.ERROR for issue in issues)


def test_no_gap_reports_the_enclosed_gap_once() -> None:
    issues = evaluate_topology_rules([RING], [TopologyRule(TopologyRuleType.NO_GAP, "ring")])

    assert _codes(issues) == [("TOP-NO-GAP", None)]


def test_no_duplicate_flags_the_repeated_geometry() -> None:
    issues = evaluate_topology_rules(
        [PARCELS], [TopologyRule(TopologyRuleType.NO_DUPLICATE, "parcels")]
    )

    assert _codes(issues) == [("TOP-NO-DUPLICATE", 1)]


def test_minimum_area_uses_the_rule_severity() -> None:
    rule = TopologyRule(
        TopologyRuleType.MINIMUM_AREA, "small", minimum_area=1.0, severity=Severity.WARNING
    )

    issues = evaluate_topology_rules([SMALL], [rule])

    assert _codes(issues) == [("TOP-MINIMUM-AREA", 0)]
    assert issues[0].severity is Severity.WARNING


def test_must_be_inside_flags_features_outside_the_reference() -> None:
    rule = TopologyRule(TopologyRuleType.MUST_BE_INSIDE, "parcels", reference_layer="area")

    issues = evaluate_topology_rules([PARCELS, AREA], [rule])

    assert _codes(issues) == [("TOP-MUST_BE_INSIDE", 1), ("TOP-MUST_BE_INSIDE", 2)]


def test_must_not_intersect_is_silent_for_distant_layers_and_flags_overlap() -> None:
    far_rule = TopologyRule(TopologyRuleType.MUST_NOT_INTERSECT, "parcels", reference_layer="far")
    near_rule = TopologyRule(TopologyRuleType.MUST_NOT_INTERSECT, "parcels", reference_layer="area")

    assert evaluate_topology_rules([PARCELS, FAR], [far_rule]) == ()
    flagged = evaluate_topology_rules([PARCELS, AREA], [near_rule])
    assert [index for _, index in _codes(flagged)] == [0, 1, 2]


def test_reference_rules_outside_the_cross_layer_pair_use_the_dispatcher() -> None:
    rule = TopologyRule(TopologyRuleType.MUST_INTERSECT, "parcels", reference_layer="far")

    issues = evaluate_topology_rules([PARCELS, FAR], [rule])

    assert {code for code, _ in _codes(issues)} == {"TOP-MUST-INTERSECT"}
    assert len(issues) == 3


def test_findings_from_several_rules_are_sorted_together() -> None:
    rules = [
        TopologyRule(TopologyRuleType.NO_OVERLAP, "parcels"),
        TopologyRule(TopologyRuleType.NO_DUPLICATE, "parcels"),
    ]

    issues = evaluate_topology_rules([PARCELS], rules)

    assert _codes(issues) == [
        ("TOP-NO-DUPLICATE", 1),
        ("TOP-NO-OVERLAP", 0),
        ("TOP-NO-OVERLAP", 0),
        ("TOP-NO-OVERLAP", 1),
    ]


def test_no_rules_yield_no_findings() -> None:
    assert evaluate_topology_rules([PARCELS], []) == ()


def test_duplicate_layer_names_are_rejected() -> None:
    rule = TopologyRule(TopologyRuleType.NO_OVERLAP, "parcels")

    with pytest.raises(ValueError, match="layer names must be unique"):
        evaluate_topology_rules([PARCELS, PARCELS], [rule])


def test_rule_on_an_unknown_layer_is_rejected() -> None:
    rule = TopologyRule(TopologyRuleType.NO_OVERLAP, "missing")

    with pytest.raises(ValueError, match="unknown layer: missing"):
        evaluate_topology_rules([PARCELS], [rule])


def test_cross_layer_rule_with_unknown_reference_is_rejected() -> None:
    rule = TopologyRule(TopologyRuleType.MUST_BE_INSIDE, "parcels", reference_layer="nowhere")

    with pytest.raises(ValueError, match="unknown reference layer: nowhere"):
        evaluate_topology_rules([PARCELS], [rule])


def test_advanced_rule_with_unknown_reference_is_rejected() -> None:
    rule = TopologyRule(TopologyRuleType.MUST_TOUCH, "parcels", reference_layer="nowhere")

    with pytest.raises(ValueError, match="unknown reference layer: nowhere"):
        evaluate_topology_rules([PARCELS], [rule])
