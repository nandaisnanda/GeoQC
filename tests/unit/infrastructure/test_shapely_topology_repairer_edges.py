"""Edge and failure behaviour of the Shapely topology repairer."""

import pytest
import shapely
from shapely import box, from_wkt
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from geoqc.domain.models.topology_repair import (
    GeometryRepairResult,
    RepairAction,
    RepairConfig,
    RepairIssueType,
    RepairStatus,
)
from geoqc.infrastructure.gis.shapely_topology_repairer import ShapelyTopologyRepairer

REPAIRER = ShapelyTopologyRepairer()
BOWTIE = "POLYGON((0 0,2 2,0 2,2 0,0 0))"
SQUARE = "POLYGON((10 10,12 10,12 12,10 12,10 10))"
BIG_A = "((0 0,10 0,10 10,0 10,0 0))"
BIG_B = "((20 0,30 0,30 10,20 10,20 0))"
TINY = "((50 50,50.001 50,50.001 50.001,50 50.001,50 50))"


def _issue_types(result: GeometryRepairResult) -> set[RepairIssueType]:
    return {action.issue_type for action in result.actions}


# -- failure handling ------------------------------------------------------


def test_repair_returns_failed_result_when_shapely_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_: object) -> None:
        raise shapely.errors.ShapelyError("boom")

    monkeypatch.setattr(ShapelyTopologyRepairer, "_repair_geometry", explode)

    result = REPAIRER.repair(BOWTIE, RepairConfig())

    assert result.status is RepairStatus.FAILED
    assert result.actions == ()
    assert result.after_wkt == result.before_wkt
    assert result.failure_reason == "Repair operation failed."


def test_coverage_failure_is_isolated_to_the_failing_feature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = ShapelyTopologyRepairer._repair_geometry
    target = from_wkt(SQUARE)

    def flaky(
        self: ShapelyTopologyRepairer, geometry: BaseGeometry, config: RepairConfig
    ) -> tuple[BaseGeometry, list[RepairAction]]:
        if geometry.equals(target):
            raise ValueError("boom")
        return original(self, geometry, config)

    monkeypatch.setattr(ShapelyTopologyRepairer, "_repair_geometry", flaky)

    result = REPAIRER.repair_coverage([BOWTIE, SQUARE], RepairConfig())

    good, bad = (item.result for item in result.report.results)
    assert good.status is RepairStatus.REPAIRED
    assert from_wkt(result.after_wkt[0]).is_valid
    assert bad.status is RepairStatus.FAILED
    assert bad.failure_reason == "boom"
    assert result.after_wkt[1] == result.before_wkt[1]


def test_coverage_failure_without_message_reports_the_error_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*_: object) -> None:
        raise ValueError

    monkeypatch.setattr(ShapelyTopologyRepairer, "_repair_geometry", explode)

    result = REPAIRER.repair_coverage([SQUARE], RepairConfig())

    assert result.report.results[0].result.failure_reason == "ValueError"


def test_cross_feature_failure_rolls_back_every_feature(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(self: ShapelyTopologyRepairer, repaired: list[BaseGeometry], *_: object) -> None:
        repaired[0] = box(0, 0, 1, 1)  # a partial edit that must not survive
        raise ValueError("boom")

    monkeypatch.setattr(ShapelyTopologyRepairer, "_resolve_overlaps", explode)
    overlapping = [box(0, 0, 2, 2).wkt, box(1, 0, 3, 2).wkt]

    result = REPAIRER.repair_coverage(overlapping, RepairConfig())

    assert result.after_wkt == result.before_wkt
    assert result.report.failed_count == 2
    for item in result.report.results:
        assert item.result.status is RepairStatus.FAILED
        assert "rolled back atomically" in (item.result.failure_reason or "")


# -- single geometry --------------------------------------------------------


def test_duplicate_vertex_removal_can_be_disabled() -> None:
    duplicated = "POLYGON((0 0,0 0,1 0,1 1,0 1,0 0))"

    result = REPAIRER.repair(duplicated, RepairConfig(remove_duplicate_vertices=False))

    assert result.status is RepairStatus.UNCHANGED
    assert result.after_wkt == result.before_wkt


def test_hole_outside_shell_is_reported_as_ring_error_only() -> None:
    hole_outside = "POLYGON((0 0,4 0,4 4,0 4,0 0),(10 10,11 10,11 11,10 11,10 10))"

    result = REPAIRER.repair(hole_outside, RepairConfig())

    assert result.status is RepairStatus.REPAIRED
    assert _issue_types(result) == {RepairIssueType.INVALID_RING}
    assert from_wkt(result.after_wkt).is_valid


def test_invalid_geometry_without_polygon_reason_falls_back_to_self_intersection() -> None:
    degenerate_line = "LINESTRING(0 0,0 0)"

    result = REPAIRER.repair(degenerate_line, RepairConfig(remove_duplicate_vertices=False))

    assert result.status is RepairStatus.REPAIRED
    assert _issue_types(result) == {RepairIssueType.SELF_INTERSECTION}
    assert result.actions[0].strategy == "make_valid"
    assert from_wkt(result.after_wkt).is_valid


def test_candidate_that_stays_invalid_is_reported_as_failed() -> None:
    bowtie_with_duplicate = "POLYGON((0 0,0 0,2 2,0 2,2 0,0 0))"

    result = REPAIRER.repair(bowtie_with_duplicate, RepairConfig(fix_invalid=False))

    assert result.status is RepairStatus.FAILED
    assert RepairIssueType.DUPLICATE_VERTEX in _issue_types(result)
    assert not from_wkt(result.after_wkt).is_valid


# -- sliver handling --------------------------------------------------------


def test_small_area_part_is_dropped_from_a_multipolygon() -> None:
    wkt = f"MULTIPOLYGON({BIG_A},{BIG_B},{TINY})"

    result = REPAIRER.repair(wkt, RepairConfig(sliver_area_threshold=1e-3))

    assert result.status is RepairStatus.REPAIRED
    assert RepairIssueType.SLIVER_POLYGON in _issue_types(result)
    after = from_wkt(result.after_wkt)
    assert isinstance(after, MultiPolygon)
    assert len(after.geoms) == 2
    assert after.area == pytest.approx(200.0)


def test_sliver_removal_keeps_non_polygon_parts_in_a_collection() -> None:
    wkt = f"GEOMETRYCOLLECTION(POLYGON{BIG_A},LINESTRING(0 20,10 20),POLYGON{TINY})"

    result = REPAIRER.repair(wkt, RepairConfig(sliver_area_threshold=1e-3))

    after = from_wkt(result.after_wkt)
    assert RepairIssueType.SLIVER_POLYGON in _issue_types(result)
    assert isinstance(after, GeometryCollection)
    assert sorted(part.geom_type for part in after.geoms) == ["LineString", "Polygon"]
    assert after.is_valid


def test_zero_perimeter_part_counts_as_a_sliver() -> None:
    wkt = f"MULTIPOLYGON({BIG_A},((5 5,5 5,5 5,5 5)))"
    config = RepairConfig(
        sliver_area_threshold=0.0, remove_duplicate_vertices=False, fix_invalid=False
    )

    result = REPAIRER.repair(wkt, config)

    assert RepairIssueType.SLIVER_POLYGON in _issue_types(result)
    assert from_wkt(result.after_wkt).area == pytest.approx(100.0)


# -- coverage repair --------------------------------------------------------


def _ring_of_squares_around_hole() -> list[str]:
    return [
        box(0, 0, 3, 1).wkt,
        box(0, 2, 3, 3).wkt,
        box(0, 1, 1, 2).wkt,
        box(2, 1, 3, 2).wkt,
    ]


def test_gap_larger_than_the_threshold_is_left_open() -> None:
    result = REPAIRER.repair_coverage(_ring_of_squares_around_hole(), RepairConfig())

    assert result.after_wkt == result.before_wkt
    assert all(item.result.status is RepairStatus.UNCHANGED for item in result.report.results)


def test_gap_without_a_neighbour_is_left_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ShapelyTopologyRepairer, "_widest_neighbour", staticmethod(lambda *_: None))

    result = REPAIRER.repair_coverage(
        _ring_of_squares_around_hole(), RepairConfig(gap_area_threshold=2.0)
    )

    assert result.after_wkt == result.before_wkt


def test_polygon_collapsing_to_a_line_is_rolled_back() -> None:
    collapses = "POLYGON((0 0,1 1,2 2,0 0))"

    result = REPAIRER.repair_coverage([collapses, SQUARE], RepairConfig())

    collapsed, untouched = (item.result for item in result.report.results)
    assert collapsed.status is RepairStatus.FAILED
    assert "non-polygon" in (collapsed.failure_reason or "")
    assert result.after_wkt[0] == result.before_wkt[0]
    assert untouched.status is RepairStatus.UNCHANGED


def test_shape_shift_limit_rejects_a_repair() -> None:
    far_sliver = f"MULTIPOLYGON({BIG_A},{TINY})"
    config = RepairConfig(sliver_area_threshold=1e-3, max_shape_shift=1.0)

    result = REPAIRER.repair_coverage([far_sliver], config)

    only = result.report.results[0].result
    assert only.status is RepairStatus.FAILED
    assert "max_shape_shift" in (only.failure_reason or "")
    assert result.after_wkt == result.before_wkt


def test_invalid_candidate_is_rolled_back_in_a_coverage() -> None:
    result = REPAIRER.repair_coverage([BOWTIE], RepairConfig(fix_invalid=False))

    only = result.report.results[0].result
    assert only.status is RepairStatus.FAILED
    assert only.failure_reason == "Candidate geometry is invalid."
    assert result.after_wkt == result.before_wkt


def test_overlap_and_gap_repair_can_be_disabled() -> None:
    overlapping = [box(0, 0, 2, 2).wkt, box(1, 0, 3, 2).wkt]
    config = RepairConfig(resolve_overlaps=False, fill_gaps=False)

    result = REPAIRER.repair_coverage(overlapping, config)

    assert result.after_wkt == result.before_wkt


def test_coverage_of_points_has_no_polygons_to_repair() -> None:
    result = REPAIRER.repair_coverage(["POINT(0 0)", "POINT(1 1)"], RepairConfig())

    assert result.after_wkt == result.before_wkt
    assert result.report.unchanged_count == 2


def test_sliver_removal_can_be_disabled() -> None:
    wkt = f"MULTIPOLYGON({BIG_A},{TINY})"

    result = REPAIRER.repair(wkt, RepairConfig(sliver_area_threshold=1e-3, remove_slivers=False))

    assert result.status is RepairStatus.UNCHANGED
    assert result.after_wkt == result.before_wkt


def test_safety_check_rejects_a_repair_that_erases_the_geometry() -> None:
    reason = REPAIRER._safety_failure(Polygon([(0, 0), (1, 0), (1, 1)]), Polygon(), RepairConfig())

    assert reason == "Candidate repair would erase the entire geometry."
