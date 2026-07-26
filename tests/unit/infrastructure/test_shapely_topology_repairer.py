"""Tests for the Shapely topology repairer."""

from shapely import box, from_wkt
from shapely.geometry import LineString, Point, Polygon

from geoqc.domain.models.topology_repair import RepairConfig, RepairIssueType, RepairStatus
from geoqc.infrastructure.gis.shapely_topology_repairer import ShapelyTopologyRepairer

REPAIRER = ShapelyTopologyRepairer()
DEFAULT = RepairConfig()


def test_self_intersection_is_made_valid() -> None:
    """A bow-tie polygon is repaired into a valid geometry."""
    bowtie = Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])

    result = REPAIRER.repair(bowtie.wkt, DEFAULT)

    assert result.status is RepairStatus.REPAIRED
    assert result.has_action(RepairIssueType.SELF_INTERSECTION)
    assert from_wkt(result.after_wkt).is_valid


def test_duplicate_vertex_is_removed() -> None:
    """Coincident consecutive vertices are dropped without changing shape."""
    duplicated = Polygon([(0, 0), (0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])

    result = REPAIRER.repair(duplicated.wkt, DEFAULT)

    assert result.has_action(RepairIssueType.DUPLICATE_VERTEX)
    assert result.metrics.vertex_count_after < result.metrics.vertex_count_before
    assert from_wkt(result.after_wkt).equals(duplicated)


def test_invalid_ring_is_classified() -> None:
    """A self-touching ring is repaired and reported as a ring error."""
    figure_eight = Polygon(
        [(0, 0), (2, 0), (2, 2), (0, 2), (0, 0), (1, 1), (1, 1.5), (0.5, 1), (1, 1)]
    )

    result = REPAIRER.repair(figure_eight.wkt, DEFAULT)

    assert result.status is RepairStatus.REPAIRED
    assert from_wkt(result.after_wkt).is_valid


def test_valid_geometry_is_unchanged() -> None:
    """A clean geometry produces an unchanged result with no actions."""
    square = box(0, 0, 1, 1)

    result = REPAIRER.repair(square.wkt, DEFAULT)

    assert result.status is RepairStatus.UNCHANGED
    assert result.actions == ()
    assert not result.is_changed
    assert result.metrics.shape_shift == 0.0


def test_sliver_part_is_removed_with_explicit_threshold() -> None:
    """A degenerate sliver part is dropped when it falls below the threshold."""
    solid = box(0, 0, 1, 1)
    sliver = Polygon([(2, 0), (2.0005, 0), (2.0005, 1), (2, 1), (2, 0)])
    multi = solid.union(sliver)
    config = RepairConfig(sliver_thinness_threshold=0.05, fix_invalid=False)

    result = REPAIRER.repair(multi.wkt, config)

    assert result.has_action(RepairIssueType.SLIVER_POLYGON)
    assert from_wkt(result.after_wkt).area < multi.area


def test_non_polygon_geometry_survives_sliver_pass() -> None:
    """Lines and points are never treated as slivers."""
    line = LineString([(0, 0), (1, 1)])

    result = REPAIRER.repair(line.wkt, DEFAULT)

    assert result.status is RepairStatus.UNCHANGED
    assert from_wkt(result.after_wkt).equals(line)


def test_point_repair_is_unchanged() -> None:
    """A valid point needs no repair."""
    result = REPAIRER.repair(Point(1, 2).wkt, DEFAULT)

    assert result.status is RepairStatus.UNCHANGED


def test_overlap_is_erased_from_later_feature() -> None:
    """The earlier feature keeps the disputed area; the later loses it."""
    first = box(0, 0, 2, 2)
    second = box(1, 0, 3, 2)

    coverage = REPAIRER.repair_coverage([first.wkt, second.wkt], DEFAULT)

    assert coverage.report.action_counts.get("overlap") == 1
    areas = [from_wkt(wkt).area for wkt in coverage.after_wkt]
    assert areas[0] == 4.0
    assert areas[1] == 2.0


def test_enclosed_gap_is_filled_into_a_neighbour() -> None:
    """A small enclosed hole is merged into an adjacent feature."""
    left = box(0, 0, 1, 2).difference(box(0.8, 0.9, 1.0, 1.1))
    right = box(1, 0, 2, 2).difference(box(1.0, 0.9, 1.2, 1.1))
    config = RepairConfig(gap_area_threshold=0.1)

    coverage = REPAIRER.repair_coverage([left.wkt, right.wkt], config)

    assert coverage.report.action_counts.get("gap") == 1
    total_area = sum(from_wkt(wkt).area for wkt in coverage.after_wkt)
    assert total_area == 4.0


def test_coverage_ignores_non_polygons_for_topology() -> None:
    """Non-polygon features pass through overlap and gap resolution."""
    point = Point(5, 5)
    square = box(0, 0, 1, 1)

    coverage = REPAIRER.repair_coverage([point.wkt, square.wkt], DEFAULT)

    assert coverage.report.total == 2
    assert coverage.report.action_counts == {}


def test_empty_geometry_is_handled_without_raising() -> None:
    """An empty geometry needs no repair and never raises."""
    empty = REPAIRER.repair("POLYGON EMPTY", DEFAULT)

    assert empty.status is RepairStatus.UNCHANGED
    assert empty.metrics.shape_shift == 0.0


def test_safety_guard_rolls_back_excessive_area_change() -> None:
    """An explicit minimal-change budget rejects and rolls back a candidate."""
    first = box(0, 0, 2, 2)
    second = box(1, 0, 3, 2)
    config = RepairConfig(max_relative_area_change=0.1)

    coverage = REPAIRER.repair_coverage([first.wkt, second.wkt], config)

    rejected = coverage.report.results[1].result
    assert rejected.status is RepairStatus.FAILED
    assert from_wkt(rejected.after_wkt).equals(second)
    assert rejected.failure_reason == "Candidate exceeds max_relative_area_change."
