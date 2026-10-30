"""Area findings report real units taken from the CRS."""

from shapely.geometry import box

from geoqc.domain.models import DatasetLayer, TopologyRule, TopologyRuleType
from geoqc.infrastructure.gis.audit_service import audit_geometries
from geoqc.infrastructure.gis.finding_builders import (
    _gap_issues,
    _minimum_area_issues,
    _overlap_issues,
)
from geoqc.infrastructure.gis.topology_service import evaluate_topology_rules

_OVERLAPPING = [box(0, 0, 10, 10), box(5, 5, 15, 15)]
_RING = [box(0, 0, 3, 1), box(0, 2, 3, 3), box(0, 1, 1, 2), box(2, 1, 3, 2)]
# Two overlapping ~100 m squares near Yogyakarta, in degrees.
_GEOGRAPHIC = [box(110.0, -7.0, 110.001, -6.999), box(110.0005, -6.9995, 110.002, -6.998)]


def test_projected_overlap_reports_square_metres() -> None:
    [issue] = _overlap_issues(_OVERLAPPING, "parcels", crs="EPSG:32749")

    assert issue.message == "Features 0 and 1 overlap by 25 m²."
    assert issue.metadata["overlap_area"] == 25.0


def test_geographic_overlap_is_measured_in_utm_and_says_so() -> None:
    [issue] = _overlap_issues(_GEOGRAPHIC, "parcels", crs="EPSG:4326")

    assert "m² (measured in EPSG:32749; the dataset CRS is geographic)" in issue.message
    area = float(issue.message.split("overlap by ")[1].split(" ")[0])
    assert 2_500 < area < 3_500


def test_gap_uses_the_crs_unit_name() -> None:
    [issue] = _gap_issues(_RING, "parcels", crs="EPSG:2263")

    assert issue.message == "Coverage contains an enclosed gap of 1 US ft²."


def test_minimum_area_names_the_unit_for_value_and_threshold() -> None:
    [issue] = _minimum_area_issues([box(0, 0, 1, 1.75)], "parcels", 5, crs="EPSG:32749")

    assert issue.message == "Feature 0 area 1.75 m² is below 5 m²."


def test_minimum_area_on_geographic_crs_keeps_threshold_in_degrees() -> None:
    [issue, _] = _minimum_area_issues(_GEOGRAPHIC, "parcels", 5, crs="EPSG:4326")

    assert "m² (measured in EPSG:32749" in issue.message
    assert issue.message.endswith("is below 5 square degrees.")


def test_missing_crs_falls_back_to_square_units() -> None:
    [issue] = _overlap_issues(_OVERLAPPING, "parcels")

    assert issue.message == "Features 0 and 1 overlap by 25 square units."


def test_audit_passes_dataset_crs_to_area_messages() -> None:
    result = audit_geometries(_OVERLAPPING, preset="parcel", crs="EPSG:32749", minimum_area=200)

    messages = {issue.issue_type: issue.message for issue in result.issues}
    assert messages["overlap"] == "Features 0 and 1 overlap by 25 m²."
    assert messages["below_minimum_area"].endswith("is below 200 m².")


def test_topology_rules_use_the_layer_crs() -> None:
    layer = DatasetLayer("parcels", tuple(item.wkt for item in _OVERLAPPING), "EPSG:32749")
    rule = TopologyRule(TopologyRuleType.NO_OVERLAP, "parcels")

    [issue] = evaluate_topology_rules((layer,), (rule,))

    assert issue.message == "Features 0 and 1 overlap by 25 m²."


def test_geographic_crs_with_out_of_range_coordinates_reports_square_degrees() -> None:
    [issue] = _overlap_issues(
        [box(500, 500, 510, 510), box(505, 505, 515, 515)], "x", crs="EPSG:4326"
    )

    assert issue.message == "Features 0 and 1 overlap by 25 square degrees."
