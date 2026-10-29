"""Hypothesis strategies that generate dirty geometries and layers.

Every geometry strategy yields Shapely objects a reader could realistically hand to
GeoQC: self-intersecting polygons, rings that were never closed in the source WKB or
WKT, empty geometries, repeated vertices, coordinates at the edge of the float range,
NaN coordinates, and layers that mix geometry types.
"""

import math
import struct
from collections.abc import Sequence

import shapely
from hypothesis import strategies as st
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.geometry.base import BaseGeometry

Coordinate = tuple[float, float]

_WKB_POINT = 1
_WKB_LINESTRING = 2
_WKB_POLYGON = 3

# Small grid values keep overlaps, touches, and duplicates likely between features.
grid_values = st.integers(min_value=-4, max_value=4).map(float)
extreme_values = st.sampled_from(
    (
        0.0,
        -0.0,
        5e-324,
        -5e-324,
        2.2250738585072014e-308,
        1e-300,
        1e300,
        -1e300,
        1.7976931348623157e308,
        -1.7976931348623157e308,
        1e15 + 0.5,
    )
)
nan_values = st.just(math.nan)

finite_values = st.one_of(
    grid_values,
    st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
)
dirty_values = st.one_of(grid_values, finite_values, extreme_values, nan_values)


def coordinates(values: st.SearchStrategy[float] = dirty_values) -> st.SearchStrategy[Coordinate]:
    return st.tuples(values, values)


def _ring_wkb(points: Sequence[Coordinate]) -> bytes:
    body = struct.pack("<I", len(points))
    for x, y in points:
        body += struct.pack("<dd", x, y)
    return body


def polygon_wkb(rings: Sequence[Sequence[Coordinate]]) -> bytes:
    """Encode a little-endian WKB polygon without validating its rings."""
    return struct.pack("<BII", 1, _WKB_POLYGON, len(rings)) + b"".join(
        _ring_wkb(ring) for ring in rings
    )


def linestring_wkb(points: Sequence[Coordinate]) -> bytes:
    return struct.pack("<BI", 1, _WKB_LINESTRING) + _ring_wkb(points)


def polygon_wkt(rings: Sequence[Sequence[Coordinate]]) -> str:
    """Encode a WKT polygon without closing or validating its rings."""
    if not rings:
        return "POLYGON EMPTY"
    body = ", ".join("(" + ", ".join(f"{x!r} {y!r}" for x, y in ring) + ")" for ring in rings)
    return f"POLYGON ({body})".replace("nan", "NaN").replace("inf", "Inf")


def parse_wkb(payload: bytes) -> BaseGeometry | None:
    """Parse WKB the way a tolerant reader would: close rings, drop the unreadable."""
    return shapely.from_wkb(payload, on_invalid="fix")


def parse_wkt(payload: str) -> BaseGeometry | None:
    return shapely.from_wkt(payload, on_invalid="fix")


@st.composite
def self_intersecting_polygons(draw: st.DrawFn) -> Polygon:
    """Bowtie and figure-eight rings, including degenerate ones."""
    x0, x1, y0, y1 = (draw(finite_values) for _ in range(4))
    shape = draw(st.sampled_from(("bowtie", "figure_eight", "spike")))
    if shape == "bowtie":
        ring = [(x0, y0), (x1, y1), (x1, y0), (x0, y1)]
    elif shape == "figure_eight":
        ring = [(x0, y0), (x1, y0), (x0, y1), (x1, y1), (x0, y0), (x0, y1), (x1, y0)]
    else:
        ring = [(x0, y0), (x1, y0), (x0, y0), (x0, y1)]
    return Polygon(ring)


unclosed_rings = st.lists(coordinates(), min_size=1, max_size=6).filter(
    lambda ring: ring[0] != ring[-1] or len(ring) == 1
)


@st.composite
def unclosed_ring_wkb(draw: st.DrawFn) -> bytes:
    """Polygon WKB whose shell or hole does not repeat its first vertex."""
    shell = draw(unclosed_rings)
    holes = draw(st.lists(unclosed_rings, max_size=2))
    return polygon_wkb([shell, *holes])


@st.composite
def unclosed_ring_wkt(draw: st.DrawFn) -> str:
    return polygon_wkt([draw(unclosed_rings)])


def _present(geometry: BaseGeometry | None) -> BaseGeometry:
    assert geometry is not None
    return geometry


def _parsed(strategy: st.SearchStrategy[BaseGeometry | None]) -> st.SearchStrategy[BaseGeometry]:
    """Keep payloads the tolerant reader could recover; it drops one-point rings."""
    return strategy.filter(lambda geometry: geometry is not None).map(_present)


unclosed_ring_geometries: st.SearchStrategy[BaseGeometry] = st.one_of(
    _parsed(unclosed_ring_wkb().map(parse_wkb)),
    _parsed(unclosed_ring_wkt().map(parse_wkt)),
)

empty_geometries: st.SearchStrategy[BaseGeometry] = st.sampled_from(
    (
        Point(),
        LineString(),
        Polygon(),
        MultiPoint(),
        MultiLineString(),
        MultiPolygon(),
        GeometryCollection(),
        shapely.from_wkt("POLYGON EMPTY"),
        GeometryCollection([Point(), Polygon()]),
    )
)


@st.composite
def duplicate_vertex_geometries(draw: st.DrawFn) -> BaseGeometry:
    """Lines and polygons that repeat vertices, including fully collapsed ones."""
    points = draw(st.lists(coordinates(finite_values), min_size=1, max_size=5))
    repeated = [point for point in points for _ in range(draw(st.integers(1, 3)))]
    if draw(st.booleans()):
        return LineString(repeated if len(repeated) > 1 else repeated * 2)
    ring = repeated + [repeated[0]] * draw(st.integers(1, 3))
    return Polygon(ring if len(ring) >= 4 else ring + [ring[0]] * (4 - len(ring)))


@st.composite
def _boxes(draw: st.DrawFn, values: st.SearchStrategy[float]) -> Polygon:
    """A box whose first vertex is on the grid.

    GEOS compares the first and last ring vertex to decide closure, and NaN never
    equals itself, so a ring that starts on NaN cannot exist as a Shapely object.
    The other corners take ``values`` freely.
    """
    x0, y0 = draw(coordinates(grid_values))
    x1, y1 = draw(coordinates(values))
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


@st.composite
def simple_geometries(
    draw: st.DrawFn, values: st.SearchStrategy[float] = dirty_values
) -> BaseGeometry:
    """Points, lines, boxes, and multi-geometries built from the given coordinates."""
    kind = draw(
        st.sampled_from(
            ("point", "line", "polygon", "multipoint", "multiline", "multipolygon", "collection")
        )
    )
    point = coordinates(values)
    if kind == "point":
        return Point(draw(point))
    if kind == "line":
        return LineString(draw(st.lists(point, min_size=2, max_size=5)))
    if kind == "polygon":
        return draw(_boxes(values))
    if kind == "multipoint":
        return MultiPoint(draw(st.lists(point, min_size=1, max_size=4)))
    if kind == "multiline":
        lines = st.lists(point, min_size=2, max_size=4)
        return MultiLineString(draw(st.lists(lines, min_size=1, max_size=3)))
    if kind == "multipolygon":
        return MultiPolygon(draw(st.lists(_boxes(values), min_size=1, max_size=3)))
    children = draw(st.lists(simple_geometries(values), min_size=1, max_size=3))
    return GeometryCollection(children)


extreme_coordinate_geometries = simple_geometries(st.one_of(extreme_values, grid_values))
nan_geometries = simple_geometries(st.one_of(nan_values, grid_values))

dirty_geometries: st.SearchStrategy[BaseGeometry] = st.one_of(
    simple_geometries(grid_values),
    self_intersecting_polygons(),
    unclosed_ring_geometries,
    empty_geometries,
    duplicate_vertex_geometries(),
    extreme_coordinate_geometries,
    nan_geometries,
)

#: A layer with mixed geometry types and every kind of dirty feature.
dirty_layers = st.lists(dirty_geometries, min_size=0, max_size=8)

#: Raw WKB cells for streaming readers, including strict-parser failures and nulls.
dirty_wkb_cells: st.SearchStrategy[bytes | None] = st.one_of(
    st.none(),
    unclosed_ring_wkb(),
    st.lists(coordinates(), min_size=0, max_size=1).map(linestring_wkb),
    dirty_geometries.map(lambda geometry: bytes(shapely.to_wkb(geometry))),
)

attribute_values = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**63), max_value=2**63 - 1),
    st.floats(),
    st.text(max_size=5),
    st.sampled_from(("active", "inactive", "", "NaN")),
)
