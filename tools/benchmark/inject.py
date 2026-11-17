"""Plan isolated defect sites on clean synthetic data, then apply one defect type at a time.

All geometry here is in the metric CRS of make_clean.py. Every injector takes a magnitude
and the audit tolerance it is measured against, and records their ratio and whether the
audit is expected to detect the defect.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import geopandas as gpd  # type: ignore[import-untyped]
from make_clean import PARCEL_SIZE
from shapely import affinity
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring
from shapely.strtree import STRtree

HERE = Path(__file__).parent
DEFAULT_RATIO = 0.5
# TOP-SLIVER flags a polygon whose compactness 4*pi*A/P^2 is under this (fixed in the audit).
SLIVER_COMPACTNESS = 0.05
# The unnoded T-junction moves the through node this far along the street, past the
# no_dangles tolerance (0.5 m), so the stem's end no longer meets a segment end.
T_JUNCTION_SHIFT = 10.0
# Clean parcel coordinates sit on this grid (bench-parcels precision_grid size, metres).
GRID = 0.001
# The precision_grid defect moves a vertex this far off the grid (metres).
OFF_GRID_SHIFT = 0.0003
# The partial duplicate copies this normalized stretch of the road.
PARTIAL_SPAN = (0.3, 0.7)
# The spike's apex sits this far outside the parcel edge.
SPIKE_LENGTH = 2.0
CSV_COLUMNS = (
    "defect_type",
    "layer",
    "feature_index",
    "related_index",
    "magnitude",
    "tolerance",
    "ratio_r",
    "crs",
    "seed",
    "expected_detect",
)

Point = tuple[float, float]
Site = tuple[tuple[int, ...], tuple[object, ...]]
"""(features the defect edits, type-specific detail)."""


@dataclass(frozen=True)
class Defect:
    """One injected defect. related_index is the other feature it touches, or -1."""

    defect_type: str
    layer: str
    feature_index: int
    related_index: int = -1
    magnitude: float | None = None
    tolerance: float | None = None
    ratio_r: float | None = None
    expected_detect: bool = True


class NotEnoughSites(ValueError):
    def __init__(self, layer: str, label: str, found: int, need: int) -> None:
        super().__init__(f"only {found} isolated {label} sites on {layer}, need {need}")
        self.layer = layer


def sliver_tolerance(length: float, compactness: float = SLIVER_COMPACTNESS) -> float:
    """Strip width at which a length x width rectangle reaches the compactness threshold.

    Solves c * (L + w)^2 = pi * L * w for the small root; narrower strips are slivers.
    """
    b = math.pi * length - 2 * compactness * length
    disc = b * b - 4 * compactness * compactness * length * length
    return 2 * compactness * length * length / (b + math.sqrt(disc))


@dataclass
class Context:
    """What an injector may read besides the site: the clean layer and a seeded RNG."""

    clean: Sequence[BaseGeometry]
    rng: random.Random
    _nodes: dict[Point, list[tuple[int, int]]] | None = field(default=None, repr=False)

    def nodes(self) -> dict[Point, list[tuple[int, int]]]:
        if self._nodes is None:
            self._nodes = _ends(cast(Sequence[LineString], self.clean))
        return self._nodes


Injector = Callable[[list[BaseGeometry], Site, "float | None", "float | None", Context], Defect]


@dataclass(frozen=True)
class Spec:
    """How one defect type is placed, sized, and scored.

    ``sites`` names the site kind plan() picks. ``profile`` is the only profile that
    scores the type. Swept types run at magnitude = ratio x tolerance; the others run
    once at ``magnitude`` (None when the defect has no size).
    """

    layer: str
    profile: str
    sites: str
    inject: Injector
    tolerance: float | None = None
    magnitude: float | None = None
    swept: bool = False
    # Largest ratio the sweep runs for this type (None: every ratio).
    max_ratio: float | None = None


def _defect(
    defect_type: str,
    layer: str,
    feature: int,
    related: int = -1,
    *,
    magnitude: float | None = None,
    tolerance: float | None = None,
    expected: bool = True,
) -> Defect:
    ratio = magnitude / tolerance if magnitude is not None and tolerance else None
    return Defect(defect_type, layer, feature, related, magnitude, tolerance, ratio, expected)


def _self_intersection(
    out: list[BaseGeometry],
    site: Site,
    magnitude: float | None,
    tolerance: float | None,
    context: Context,
) -> Defect:
    (index,), _ = site
    x0, y0, x1, y1 = out[index].bounds
    out[index] = Polygon([(x0, y0), (x1, y1), (x1, y0), (x0, y1)])
    return _defect("self_intersection", "parcels", index)


def _sliver(
    out: list[BaseGeometry],
    site: Site,
    magnitude: float | None,
    tolerance: float | None,
    context: Context,
) -> Defect:
    # Cut a strip off the donor's north edge and add it as a new feature, so coverage
    # stays gap-free and overlap-free. Narrower than the tolerance = a sliver.
    assert magnitude is not None and tolerance is not None
    (index,), _ = site
    x0, y0, x1, y1 = out[index].bounds
    out[index] = box(x0, y0, x1, y1 - magnitude)
    out.append(box(x0, y1 - magnitude, x1, y1))
    return _defect(
        "sliver",
        "parcels",
        len(out) - 1,
        index,
        magnitude=magnitude,
        tolerance=tolerance,
        expected=magnitude < tolerance,
    )


def _overlap(
    out: list[BaseGeometry],
    site: Site,
    magnitude: float | None,
    tolerance: float | None,
    context: Context,
) -> Defect:
    # Widen the parcel east into its neighbour by magnitude / height.
    assert magnitude is not None and tolerance is not None
    (index, neighbour), _ = site
    x0, y0, x1, y1 = out[index].bounds
    out[index] = box(x0, y0, x1 + magnitude / (y1 - y0), y1)
    return _defect(
        "overlap",
        "parcels",
        index,
        neighbour,
        magnitude=magnitude,
        tolerance=tolerance,
        expected=magnitude > tolerance,
    )


def _duplicate_vertex(
    out: list[BaseGeometry],
    site: Site,
    magnitude: float | None,
    tolerance: float | None,
    context: Context,
) -> Defect:
    (index,), _ = site
    polygon = out[index]
    assert isinstance(polygon, Polygon)
    ring = list(polygon.exterior.coords)
    out[index] = Polygon([ring[0], *ring[:-1]])
    return _defect("duplicate_vertex", "parcels", index)


def _unnoded_t_junction(
    out: list[BaseGeometry],
    site: Site,
    magnitude: float | None,
    tolerance: float | None,
    context: Context,
) -> Defect:
    # Extend the through segment a past the node and shorten b to match: a and b still
    # meet, collinear, but the stem now ends on a's interior with no vertex.
    (a, b, stem), detail = site
    node = cast(Point, detail[0])
    lines = cast(Sequence[LineString], context.clean)
    ends = dict(context.nodes()[node])
    far_a, far_b = _far_end(lines[a], ends[a]), _far_end(lines[b], ends[b])
    step = T_JUNCTION_SHIFT / math.dist(node, far_b)
    moved = (node[0] + (far_b[0] - node[0]) * step, node[1] + (far_b[1] - node[1]) * step)
    out[a] = LineString([far_a, moved])
    out[b] = LineString([moved, far_b])
    return _defect("unnoded_t_junction", "roads", stem, a)


def _undershoot(
    out: list[BaseGeometry],
    site: Site,
    magnitude: float | None,
    tolerance: float | None,
    context: Context,
) -> Defect:
    # Pull one end back from a four-way crossing by magnitude metres.
    assert magnitude is not None and tolerance is not None
    (index,), detail = site
    end = cast(int, detail[0])
    line = out[index]
    assert isinstance(line, LineString)
    coords = [(float(x), float(y)) for x, y in line.coords]
    (nx, ny), (fx, fy) = coords[end], _far_end(line, end)
    length = math.hypot(fx - nx, fy - ny)
    if magnitude >= length:
        raise ValueError(f"undershoot gap {magnitude} m exceeds segment length {length} m")
    coords[end] = (nx + (fx - nx) * magnitude / length, ny + (fy - ny) * magnitude / length)
    out[index] = LineString(coords)
    return _defect(
        "undershoot",
        "roads",
        index,
        magnitude=magnitude,
        tolerance=tolerance,
        expected=0 < magnitude <= tolerance,
    )


def _overshoot(
    out: list[BaseGeometry],
    site: Site,
    magnitude: float | None,
    tolerance: float | None,
    context: Context,
) -> Defect:
    # Push the stem's end p, which sits on the through road, `magnitude` metres further
    # along the stem's own direction: p' = p + s * unit(p - p_prev). The stem now crosses
    # the through road at p and overshoots it by s.
    assert magnitude is not None and tolerance is not None
    (through, _, stem), detail = site
    node = cast(Point, detail[0])
    end = dict(context.nodes()[node])[stem]
    line = out[stem]
    assert isinstance(line, LineString)
    coords = [(float(x), float(y)) for x, y in line.coords]
    (px, py), (qx, qy) = coords[end], coords[1 if end == 0 else -2]
    length = math.hypot(px - qx, py - qy)
    coords[end] = (px + (px - qx) * magnitude / length, py + (py - qy) * magnitude / length)
    out[stem] = LineString(coords)
    return _defect(
        "overshoot",
        "roads",
        stem,
        through,
        magnitude=magnitude,
        tolerance=tolerance,
        expected=magnitude < tolerance,
    )


def _duplicate_segment_full(
    out: list[BaseGeometry],
    site: Site,
    magnitude: float | None,
    tolerance: float | None,
    context: Context,
) -> Defect:
    # Append an exact copy of the road. magnitude = copy length / road length.
    (index,), _ = site
    out.append(out[index])
    return _defect("duplicate_segment_full", "roads", index, len(out) - 1, magnitude=magnitude)


def _duplicate_segment_partial(
    out: list[BaseGeometry],
    site: Site,
    magnitude: float | None,
    tolerance: float | None,
    context: Context,
) -> Defect:
    # Append a copy of the middle 40% of the road. The analyzer divides the shared
    # length by the SHORTER line, so its overlap ratio is 1.0 >= 0.98: by that ratio
    # the copy is a duplicate, hence expected_detect = True. (The analyzer also requires
    # a Hausdorff distance <= 1e-8, which a contained part cannot meet.)
    (index,), _ = site
    out.append(substring(out[index], *PARTIAL_SPAN, normalized=True))
    return _defect("duplicate_segment_partial", "roads", index, len(out) - 1, magnitude=magnitude)


def _gap(
    out: list[BaseGeometry],
    site: Site,
    magnitude: float | None,
    tolerance: float | None,
    context: Context,
) -> Defect:
    # Pull A back from its shared edge with B by w = area / edge length. Both parcels are
    # interior, so the parcels around them close the strip: an enclosed gap of exactly
    # `magnitude` square metres. A flat cap keeps A rectangular (no arc vertices).
    assert magnitude is not None and tolerance is not None
    (a, b), _ = site
    edge = out[a].intersection(out[b])
    width = magnitude / edge.length
    out[a] = out[a].difference(edge.buffer(width, cap_style="flat"))
    return _defect(
        "gap",
        "parcels",
        a,
        b,
        magnitude=magnitude,
        tolerance=tolerance,
        expected=0 < magnitude <= tolerance,
    )


def _duplicate_exact(
    out: list[BaseGeometry],
    site: Site,
    magnitude: float | None,
    tolerance: float | None,
    context: Context,
) -> Defect:
    # Append an exact copy of the parcel.
    (index,), _ = site
    out.append(out[index])
    # feature_index names the original (a unique isolated site), related_index the copy.
    return _defect(
        "duplicate_exact",
        "parcels",
        index,
        len(out) - 1,
        magnitude=magnitude,
        tolerance=tolerance,
        expected=True,
    )


def _duplicate_jitter(
    out: list[BaseGeometry],
    site: Site,
    magnitude: float | None,
    tolerance: float | None,
    context: Context,
) -> Defect:
    # Append a copy with every vertex moved `magnitude` metres in a random direction.
    # The baseline duplicate check compares exactly (tolerance 0): not expected to fire.
    assert magnitude is not None and tolerance is not None
    (index,), _ = site
    polygon = out[index]
    assert isinstance(polygon, Polygon)
    ring = []
    for x, y in list(polygon.exterior.coords)[:-1]:
        angle = context.rng.uniform(0.0, 2 * math.pi)
        ring.append((x + magnitude * math.cos(angle), y + magnitude * math.sin(angle)))
    out.append(Polygon(ring))
    return _defect(
        "duplicate_jitter",
        "parcels",
        index,
        len(out) - 1,
        magnitude=magnitude,
        tolerance=tolerance,
        expected=magnitude <= tolerance,
    )


def _minimum_area(
    out: list[BaseGeometry],
    site: Site,
    magnitude: float | None,
    tolerance: float | None,
    context: Context,
) -> Defect:
    # Shrink the parcel about its centroid to an area of `magnitude` square metres.
    assert magnitude is not None and tolerance is not None
    (index,), _ = site
    factor = math.sqrt(magnitude / out[index].area)
    out[index] = affinity.scale(out[index], factor, factor, origin="centroid")
    return _defect(
        "minimum_area",
        "parcels",
        index,
        magnitude=magnitude,
        tolerance=tolerance,
        expected=magnitude < tolerance,
    )


def _empty_polygon(
    out: list[BaseGeometry],
    site: Site,
    magnitude: float | None,
    tolerance: float | None,
    context: Context,
) -> Defect:
    (index,), _ = site
    out[index] = Polygon()
    return _defect("empty_polygon", "parcels", index)


def _null_geometry(
    out: list[BaseGeometry],
    site: Site,
    magnitude: float | None,
    tolerance: float | None,
    context: Context,
) -> Defect:
    (index,), _ = site
    out[index] = cast(BaseGeometry, None)
    return _defect("null_geometry", "parcels", index)


def _spike(
    out: list[BaseGeometry],
    site: Site,
    magnitude: float | None,
    tolerance: float | None,
    context: Context,
) -> Defect:
    # Replace the middle of the east edge with a triangle pointing into the neighbour:
    # base vertices at midpoint -/+ b/2, apex SPIKE_LENGTH out. `magnitude` is the apex
    # angle in degrees, so b/2 = L * tan(theta / 2). The base vertices are off the
    # 0.001 m grid (snapping them would change the angle by up to 5e-4 rad).
    assert magnitude is not None and tolerance is not None
    (index, neighbour), _ = site
    x0, y0, x1, y1 = out[index].bounds
    half = SPIKE_LENGTH * math.tan(math.radians(magnitude) / 2)
    middle = (y0 + y1) / 2
    out[index] = Polygon(
        [
            (x0, y0),
            (x1, y0),
            (x1, middle - half),
            (x1 + SPIKE_LENGTH, middle),
            (x1, middle + half),
            (x1, y1),
            (x0, y1),
        ]
    )
    return _defect(
        "spike",
        "parcels",
        index,
        neighbour,
        magnitude=magnitude,
        tolerance=tolerance,
        expected=magnitude < tolerance,
    )


def _on_grid(value: float) -> bool:
    return abs(value / GRID - round(value / GRID)) < 1e-6


def _min_vertex_distance(
    out: list[BaseGeometry],
    site: Site,
    magnitude: float | None,
    tolerance: float | None,
    context: Context,
) -> Defect:
    # Insert a vertex on the south edge, `magnitude` metres east of the south-west
    # corner: adjacent to the corner, collinear, so the shape does not change. The edge
    # runs along x, where floats near 430,000 resolve 6e-11 m; the new x is snapped to
    # the grid when the distance is a multiple of the grid step, else left off grid.
    assert magnitude is not None and tolerance is not None
    (index,), _ = site
    polygon = out[index]
    assert isinstance(polygon, Polygon)
    x0, y0, x1, y1 = polygon.bounds
    x = x0 + magnitude
    if _on_grid(magnitude):
        x = round(x / GRID) * GRID
    out[index] = Polygon([(x1, y0), (x1, y1), (x0, y1), (x0, y0), (x, y0)])
    # Record the distance as placed (x - x0 is exact in floats), within 6e-11 of nominal.
    return _defect(
        "min_vertex_distance",
        "parcels",
        index,
        magnitude=x - x0,
        tolerance=tolerance,
        expected=magnitude < tolerance,
    )


def _precision_grid(
    out: list[BaseGeometry],
    site: Site,
    magnitude: float | None,
    tolerance: float | None,
    context: Context,
) -> Defect:
    # Move the south-west corner `magnitude` metres west, off the grid. Moving outward
    # leaves a 0.003 m2 overlap with the west neighbour and no gap.
    assert magnitude is not None and tolerance is not None
    (index,), _ = site
    x0, y0, x1, y1 = out[index].bounds
    out[index] = Polygon([(x1, y0), (x1, y1), (x0, y1), (x0 - magnitude, y0)])
    return _defect(
        "precision_grid", "parcels", index, magnitude=magnitude, tolerance=tolerance, expected=True
    )


SPECS: dict[str, Spec] = {
    # Exact geometry check: no size.
    "self_intersection": Spec("parcels", "generic-polygon", "single", _self_intersection),
    # TOP-SLIVER's compactness threshold expressed as a strip width for a 20 m parcel.
    "sliver": Spec(
        "parcels",
        "generic-polygon",
        "single",
        _sliver,
        tolerance=sliver_tolerance(PARCEL_SIZE),
        swept=True,
    ),
    # generic-polygon passes profile.tolerance = 0 to the overlap check, so no ratio
    # exists: one magnitude (a 2 m wide strip of a 20 m parcel, in square metres).
    "overlap": Spec(
        "parcels",
        "generic-polygon",
        "east_pair",
        _overlap,
        tolerance=0.0,
        magnitude=2.0 * PARCEL_SIZE,
    ),
    "duplicate_vertex": Spec("parcels", "generic-polygon", "single", _duplicate_vertex),
    # jalan: no_dangles finds the stem's end; an exact touch test titles it.
    "unnoded_t_junction": Spec("roads", "jalan", "t_junction", _unnoded_t_junction),
    # jalan: no_overshoot_undershoot tolerance, also the radius _merge_road_endpoints uses
    # to title an unconnected end "Possible undershoot".
    "undershoot": Spec("roads", "jalan", "crossing_end", _undershoot, tolerance=2.0, swept=True),
    # jalan no_overshoot_undershoot: an overshoot longer than 2 m is a through road.
    "overshoot": Spec("roads", "jalan", "t_junction", _overshoot, tolerance=2.0, swept=True),
    # ROAD-DUPLICATE_SEGMENT: analyzer constants (Hausdorff 1e-8, overlap ratio 0.98),
    # not configurable, so no ratio. magnitude = copy length / road length.
    "duplicate_segment_full": Spec(
        "roads", "jalan", "road_single", _duplicate_segment_full, magnitude=1.0
    ),
    "duplicate_segment_partial": Spec(
        "roads",
        "jalan",
        "road_single",
        _duplicate_segment_partial,
        magnitude=PARTIAL_SPAN[1] - PARTIAL_SPAN[0],
    ),
    # bench-parcels no_gap: tolerance is the MAXIMUM gap area reported (1.0 m²).
    "gap": Spec("parcels", "bench-parcels", "interior_pair", _gap, tolerance=1.0, swept=True),
    # Baseline TOP-NO-DUPLICATE: topological equality, tolerance 0, in every profile.
    "duplicate_exact": Spec(
        "parcels", "bench-parcels", "single", _duplicate_exact, tolerance=0.0, magnitude=0.0
    ),
    # One jitter size (1 cm): with tolerance 0 there is no ratio to sweep.
    "duplicate_jitter": Spec(
        "parcels", "bench-parcels", "single", _duplicate_jitter, tolerance=0.0, magnitude=0.01
    ),
    # bench-parcels minimum_area: 10 m²; magnitude is the shrunken area.
    "minimum_area": Spec(
        "parcels", "bench-parcels", "single", _minimum_area, tolerance=10.0, swept=True
    ),
    # GEO-EMPTY_GEOMETRY is always on: no size.
    "empty_polygon": Spec("parcels", "bench-parcels", "single", _empty_polygon),
    "null_geometry": Spec("parcels", "bench-parcels", "single", _null_geometry),
    # bench-parcels no_spikes: minimum angle 10 degrees; magnitude is the apex angle.
    "spike": Spec(
        "parcels", "bench-parcels", "east_pair", _spike, tolerance=10.0, swept=True, max_ratio=2.0
    ),
    # bench-parcels minimum_vertex_distance: 0.05 m; magnitude is the vertex spacing.
    "min_vertex_distance": Spec(
        "parcels", "bench-parcels", "single", _min_vertex_distance, tolerance=0.05, swept=True
    ),
    # bench-parcels precision_grid: 0.001 m grid, deviation tolerance 1e-9. One magnitude.
    "precision_grid": Spec(
        "parcels",
        "bench-parcels",
        "single",
        _precision_grid,
        tolerance=1e-9,
        magnitude=OFF_GRID_SHIFT,
    ),
}
# Subtypes scored by one finding code share a family; CODE_TO_DEFECT in run.py maps
# codes to families.
FAMILY = {
    "duplicate_exact": "duplicate",
    "duplicate_jitter": "duplicate",
    "empty_polygon": "empty",
    "null_geometry": "empty",
    "duplicate_segment_full": "duplicate_segment",
    "duplicate_segment_partial": "duplicate_segment",
}
DEFECT_TYPES = tuple(SPECS)
LAYER_OF = {name: spec.layer for name, spec in SPECS.items()}
PROFILE_OF = {name: spec.profile for name, spec in SPECS.items()}
SWEPT = frozenset(name for name, spec in SPECS.items() if spec.swept)


def _neighbours(geometries: Sequence[BaseGeometry]) -> list[frozenset[int]]:
    """Features each feature touches, corners included."""
    tree = STRtree(geometries)
    return [
        frozenset(int(j) for j in tree.query(geometry, predicate="intersects") if int(j) != i)
        for i, geometry in enumerate(geometries)
    ]


def _pick(
    candidates: Iterable[Site],
    count: int,
    excluded: set[int],
    neighbours: Sequence[frozenset[int]],
    layer: str,
    label: str,
) -> list[Site]:
    """Take sites in order whose features are free, then exclude them and their neighbours."""
    chosen: list[Site] = []
    for features, detail in candidates:
        if len(chosen) == count:
            break
        if excluded.intersection(features):
            continue
        chosen.append((features, detail))
        for feature in features:
            excluded.add(feature)
            excluded.update(neighbours[feature])
    if len(chosen) < count:
        raise NotEnoughSites(layer, label, len(chosen), count)
    return chosen


def _east_of(parcels: Sequence[BaseGeometry], index: int) -> int | None:
    _, y0, x1, _ = parcels[index].bounds
    nxt = index + 1
    if nxt < len(parcels) and parcels[nxt].bounds[0] == x1 and parcels[nxt].bounds[1] == y0:
        return nxt
    return None


def _key(point: Point) -> Point:
    return (round(point[0], 6), round(point[1], 6))


def _ends(lines: Sequence[LineString]) -> dict[Point, list[tuple[int, int]]]:
    """Map each endpoint to (feature, end) pairs, end 0 = start, -1 = finish."""
    nodes: dict[Point, list[tuple[int, int]]] = {}
    for index, line in enumerate(lines):
        coords = list(line.coords)
        for end in (0, -1):
            x, y = coords[end]
            nodes.setdefault(_key((x, y)), []).append((index, end))
    return nodes


def _far_end(line: LineString, end: int) -> Point:
    coords = list(line.coords)
    x, y = coords[-1 if end == 0 else 0]
    return (x, y)


def _through_pair(
    node: Point, members: list[tuple[int, int]], lines: Sequence[LineString]
) -> tuple[int, int, int] | None:
    """For a degree-3 node, return (through_a, through_b, stem) if two members are collinear."""
    for k, (a, end_a) in enumerate(members):
        for b, end_b in members[k + 1 :]:
            ax, ay = _far_end(lines[a], end_a)
            bx, by = _far_end(lines[b], end_b)
            ua = (ax - node[0], ay - node[1])
            ub = (bx - node[0], by - node[1])
            cross = ua[0] * ub[1] - ua[1] * ub[0]
            dot = ua[0] * ub[0] + ua[1] * ub[1]
            if abs(cross) < 1e-6 and dot < 0:
                (stem,) = [index for index, _ in members if index not in (a, b)]
                return a, b, stem
    return None


def _parcel_candidates(
    parcels: Sequence[BaseGeometry], order: Sequence[int], near: Sequence[frozenset[int]]
) -> dict[str, list[Site]]:
    """Candidate sites per site kind, in the shuffled parcel order."""
    pairs = [(i, east) for i in order if (east := _east_of(parcels, i)) is not None]
    return {
        "single": [((i,), ()) for i in order],
        "east_pair": [(pair, ()) for pair in pairs],
        # Both parcels touch eight others, so neither is on the grid edge.
        "interior_pair": [(pair, ()) for pair in pairs if all(len(near[i]) == 8 for i in pair)],
    }


def _road_candidates(roads: Sequence[LineString], rng: random.Random) -> dict[str, list[Site]]:
    """Candidate sites per site kind for roads; consumes rng in a fixed order."""
    nodes = _ends(roads)
    junctions: list[Site] = []
    for node in sorted(nodes):
        members = nodes[node]
        pair = _through_pair(node, members, roads) if len(members) == 3 else None
        if pair is not None:
            junctions.append((pair, (node,)))
    rng.shuffle(junctions)
    crossings = [node for node in sorted(nodes) if len(nodes[node]) == 4]
    rng.shuffle(crossings)
    ends: list[Site] = []
    for node in crossings:
        index, end = rng.choice(nodes[node])
        ends.append(((index,), (end,)))
    # Roads joined to the network at both ends (not the cul-de-sacs), in a seeded order.
    joined = [
        ((index,), ())
        for index, line in enumerate(roads)
        if all(len(nodes[_key((x, y))]) > 1 for x, y in (line.coords[0], line.coords[-1]))
    ]
    rng.shuffle(joined)
    return {"t_junction": junctions, "crossing_end": ends, "road_single": joined}


def plan(
    parcels: Sequence[BaseGeometry],
    roads: Sequence[LineString],
    per_type: int,
    seed: int,
) -> dict[str, list[Site]]:
    """Pick per_type isolated sites for every defect type, shared across types.

    A site's features and every feature touching them are excluded from later picks,
    on that layer and across types, so no two defects touch. Types pick in SPECS order.
    Raises NotEnoughSites when the grid is too small.
    """
    rng = random.Random(seed)
    order = list(range(len(parcels)))
    rng.shuffle(order)
    near = {"parcels": _neighbours(parcels), "roads": _neighbours(roads)}
    candidates = {
        "parcels": _parcel_candidates(parcels, order, near["parcels"]),
        "roads": _road_candidates(roads, rng),
    }
    excluded: dict[str, set[int]] = {"parcels": set(), "roads": set()}
    return {
        name: _pick(
            candidates[spec.layer][spec.sites],
            per_type,
            excluded[spec.layer],
            near[spec.layer],
            spec.layer,
            name,
        )
        for name, spec in SPECS.items()
    }


def apply(
    defect_type: str,
    sites: Sequence[Site],
    geometries: Sequence[BaseGeometry],
    magnitude: float | None,
    tolerance: float | None,
    seed: int = 0,
) -> tuple[list[BaseGeometry | None], list[Defect]]:
    """Return the layer with one defect per site, and the defects.

    Feature indices stay stable; injectors that add a feature append it.
    """
    out: list[BaseGeometry] = list(geometries)
    context = Context(geometries, random.Random(f"{defect_type}:{seed}"))
    inject = SPECS[defect_type].inject
    defects = [inject(out, site, magnitude, tolerance, context) for site in sites]
    return cast(list["BaseGeometry | None"], out), defects


def magnitudes(
    defect_type: str, ratios: Sequence[float]
) -> list[tuple[float | None, float | None]]:
    """(ratio, magnitude) per file: one per ratio for swept types, else one at the fixed size."""
    spec = SPECS[defect_type]
    if spec.swept:
        assert spec.tolerance is not None
        return [
            (ratio, ratio * spec.tolerance)
            for ratio in ratios
            if spec.max_ratio is None or ratio <= spec.max_ratio
        ]
    return [(None, spec.magnitude)]


def truth_record(defect: Defect, crs: str, seed: int) -> dict[str, object]:
    def number(value: float | None) -> str:
        return "" if value is None else f"{value:.6g}"

    return {
        "defect_type": defect.defect_type,
        "layer": defect.layer,
        "feature_index": defect.feature_index,
        "related_index": defect.related_index,
        "magnitude": number(defect.magnitude),
        "tolerance": number(defect.tolerance),
        "ratio_r": number(defect.ratio_r),
        "crs": crs,
        "seed": seed,
        "expected_detect": defect.expected_detect,
    }


def write_truth(path: Path, rows: Iterable[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", type=Path, default=HERE / "out" / "clean.gpkg")
    parser.add_argument("--out", type=Path, default=HERE / "out" / "defects")
    parser.add_argument("--per-type", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--ratio", type=float, default=DEFAULT_RATIO)
    args = parser.parse_args()
    frames = {layer: gpd.read_file(args.clean, layer=layer) for layer in ("parcels", "roads")}
    sites = plan(
        list(frames["parcels"].geometry), list(frames["roads"].geometry), args.per_type, args.seed
    )
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for defect_type, spec in SPECS.items():
        ((_, magnitude),) = magnitudes(defect_type, [args.ratio])
        geometries, defects = apply(
            defect_type,
            sites[defect_type],
            list(frames[spec.layer].geometry),
            magnitude,
            spec.tolerance,
            args.seed,
        )
        path = args.out / f"{defect_type}.gpkg"
        path.unlink(missing_ok=True)
        gpd.GeoDataFrame(geometry=geometries, crs=frames[spec.layer].crs).to_file(
            path, layer=spec.layer, driver="GPKG"
        )
        crs = frames[spec.layer].crs.to_string()
        rows += [truth_record(item, crs, args.seed) for item in defects]
    write_truth(args.out / "truth.csv", rows)
    print(f"Wrote {len(SPECS)} files and truth.csv ({len(rows)} defects) to {args.out}")


if __name__ == "__main__":
    main()
