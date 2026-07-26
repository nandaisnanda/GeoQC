"""Unit tests for Shapely-based geometry validation."""

import warnings

import pytest
from shapely import from_wkt
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)

from geoqc.domain.models import GeometryIssueType
from geoqc.infrastructure.gis.shapely_geometry_validator import ShapelyGeometryValidator


@pytest.fixture
def validator() -> ShapelyGeometryValidator:
    """Return a stateless validator instance."""
    return ShapelyGeometryValidator()


def test_accepts_valid_geometry(validator: ShapelyGeometryValidator) -> None:
    """A simple valid polygon has no findings; its closing vertex is required."""
    result = validator.validate(Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]))

    assert result.is_valid
    assert result.geometry_type == "Polygon"
    assert result.issues == ()


def test_single_point_has_no_duplicate_vertex(
    validator: ShapelyGeometryValidator,
) -> None:
    """A one-coordinate sequence cannot contain a duplicate."""
    result = validator.validate(Point(1, 1))

    assert result.is_valid
    assert not result.has_issue(GeometryIssueType.DUPLICATE_VERTEX)


def test_detects_empty_geometry(validator: ShapelyGeometryValidator) -> None:
    """An empty geometry is reported even though GEOS considers it valid."""
    result = validator.validate(Point())

    assert not result.is_valid
    assert result.has_issue(GeometryIssueType.EMPTY_GEOMETRY)
    assert not result.has_issue(GeometryIssueType.INVALID_GEOMETRY)


def test_detects_invalid_self_intersection(validator: ShapelyGeometryValidator) -> None:
    """A bow-tie polygon reports both general invalidity and its specific cause."""
    bow_tie = Polygon([(0, 0), (2, 2), (0, 2), (2, 0)])

    result = validator.validate(bow_tie)

    assert result.has_issue(GeometryIssueType.INVALID_GEOMETRY)
    assert result.has_issue(GeometryIssueType.SELF_INTERSECTION)


def test_detects_self_intersection_in_valid_line(
    validator: ShapelyGeometryValidator,
) -> None:
    """Non-simple lines are self-intersecting even though GEOS calls them valid."""
    crossing_line = LineString([(0, 0), (2, 2), (0, 2), (2, 0)])

    result = validator.validate(crossing_line)

    assert crossing_line.is_valid
    assert result.has_issue(GeometryIssueType.SELF_INTERSECTION)
    assert not result.has_issue(GeometryIssueType.INVALID_GEOMETRY)


def test_line_self_intersection_has_meaningful_diagnostic(
    validator: ShapelyGeometryValidator,
) -> None:
    """Line diagnostics must not misleadingly claim that the geometry is valid."""
    result = validator.validate(LineString([(0, 0), (2, 2), (0, 2), (2, 0)]))

    issue = next(
        issue for issue in result.issues if issue.issue_type is GeometryIssueType.SELF_INTERSECTION
    )
    assert "not simple" in issue.message
    assert "Valid Geometry" not in issue.message


def test_detects_intersection_between_multiline_members(
    validator: ShapelyGeometryValidator,
) -> None:
    """Crossings between individually simple line members are still detected."""
    geometry = MultiLineString([[(0, 0), (2, 2)], [(0, 2), (2, 0)]])

    result = validator.validate(geometry)

    assert result.has_issue(GeometryIssueType.SELF_INTERSECTION)


def test_detects_polygon_ring_error(validator: ShapelyGeometryValidator) -> None:
    """A hole outside its shell is classified as a polygon ring error."""
    polygon = Polygon(
        shell=[(0, 0), (4, 0), (4, 4), (0, 4)],
        holes=[[(5, 5), (6, 5), (6, 6), (5, 6)]],
    )

    result = validator.validate(polygon)

    assert result.has_issue(GeometryIssueType.INVALID_GEOMETRY)
    assert result.has_issue(GeometryIssueType.RING_ERROR)


def test_classifies_ring_self_intersection_as_both_specific_issues(
    validator: ShapelyGeometryValidator,
) -> None:
    """A self-crossing ring is both a ring defect and a self-intersection."""
    polygon = Polygon([(0, 0), (0, 2), (1, 1), (2, 2), (2, 0), (1, 1)])

    result = validator.validate(polygon)

    assert result.has_issue(GeometryIssueType.RING_ERROR)
    assert result.has_issue(GeometryIssueType.SELF_INTERSECTION)


def test_detects_duplicate_vertex_without_counting_ring_closure(
    validator: ShapelyGeometryValidator,
) -> None:
    """Repeated line vertices are defects, unlike a polygon's closing coordinate."""
    result = validator.validate(LineString([(0, 0), (1, 1), (1, 1), (2, 2)]))

    assert result.has_issue(GeometryIssueType.DUPLICATE_VERTEX)


def test_does_not_count_closed_linestring_endpoint_as_duplicate(
    validator: ShapelyGeometryValidator,
) -> None:
    """A closed line's final coordinate is structural even when the line is non-simple."""
    result = validator.validate(LineString([(0, 0), (1, 0), (0, 0)]))

    assert not result.has_issue(GeometryIssueType.DUPLICATE_VERTEX)


def test_invalid_short_line_is_not_classified_as_ring_error(
    validator: ShapelyGeometryValidator,
) -> None:
    """A GEOS 'too few points' reason is a ring error only for polygonal input."""
    result = validator.validate(LineString([(0, 0), (0, 0)]))

    assert result.has_issue(GeometryIssueType.INVALID_GEOMETRY)
    assert not result.has_issue(GeometryIssueType.RING_ERROR)
    assert result.has_issue(GeometryIssueType.DUPLICATE_VERTEX)


def test_invalid_coordinate_does_not_emit_geos_runtime_warning(
    validator: ShapelyGeometryValidator,
) -> None:
    """Simplicity is undefined for invalid coordinates and must not be evaluated."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        geometry = from_wkt("LINESTRING (0 0, NaN 1, 2 2)")

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = validator.validate(geometry)

    assert result.has_issue(GeometryIssueType.INVALID_GEOMETRY)
    assert not result.has_issue(GeometryIssueType.SELF_INTERSECTION)


def test_detects_duplicate_vertex_recursively(validator: ShapelyGeometryValidator) -> None:
    """Multipart and collection members are traversed recursively."""
    geometry = GeometryCollection(
        [
            Point(1, 1),
            MultiPolygon([Polygon([(0, 0), (2, 0), (2, 2), (2, 0), (0, 2)])]),
        ]
    )

    result = validator.validate(geometry)

    duplicate = next(
        issue for issue in result.issues if issue.issue_type is GeometryIssueType.DUPLICATE_VERTEX
    )
    assert "geometry.geoms[1].geoms[0].exterior" in duplicate.message


def test_caps_duplicate_location_diagnostic(
    validator: ShapelyGeometryValidator,
) -> None:
    """Diagnostics stay bounded for datasets with many defective components."""
    geometry = GeometryCollection(
        [LineString([(index, 0), (index, 0), (index, 1)]) for index in range(21)]
    )

    result = validator.validate(geometry)

    duplicate = next(
        issue for issue in result.issues if issue.issue_type is GeometryIssueType.DUPLICATE_VERTEX
    )
    assert "geometry.geoms[19]" in duplicate.message
    assert "geometry.geoms[20]" not in duplicate.message
    assert "additional locations" in duplicate.message


def test_detects_duplicate_multipoint_coordinates(
    validator: ShapelyGeometryValidator,
) -> None:
    """Repeated point members are duplicate vertices despite separate components."""
    result = validator.validate(MultiPoint([(0, 0), (1, 1), (0, 0)]))

    assert result.has_issue(GeometryIssueType.DUPLICATE_VERTEX)


def test_detects_self_intersection_inside_collection(
    validator: ShapelyGeometryValidator,
) -> None:
    """Line simplicity checks recurse into heterogeneous collections."""
    geometry = GeometryCollection([Point(1, 1), LineString([(0, 0), (2, 2), (0, 2), (2, 0)])])

    result = validator.validate(geometry)

    assert result.has_issue(GeometryIssueType.SELF_INTERSECTION)


def test_detects_crossing_between_lines_inside_collection(
    validator: ShapelyGeometryValidator,
) -> None:
    """Line members are checked together across a heterogeneous collection."""
    geometry = GeometryCollection(
        [
            Point(1, 0),
            LineString([(0, 0), (2, 2)]),
            LineString([(0, 2), (2, 0)]),
        ]
    )

    result = validator.validate(geometry)

    assert result.has_issue(GeometryIssueType.SELF_INTERSECTION)


def test_allows_shared_multiline_endpoints(validator: ShapelyGeometryValidator) -> None:
    """A shared endpoint is valid line topology, not a self-intersection."""
    geometry = MultiLineString([[(0, 0), (1, 1)], [(1, 1), (2, 0)]])

    result = validator.validate(geometry)

    assert not result.has_issue(GeometryIssueType.SELF_INTERSECTION)


def test_rejects_non_shapely_input(validator: ShapelyGeometryValidator) -> None:
    """Invalid API input fails with an explicit type error."""
    with pytest.raises(TypeError, match="Shapely BaseGeometry"):
        validator.validate(None)  # type: ignore[arg-type]
