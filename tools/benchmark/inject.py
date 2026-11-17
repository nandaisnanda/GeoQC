"""Plan isolated defect sites on clean synthetic data, then apply one defect type at a time.

All geometry here is in the metric CRS of make_clean.py. Every defect records its
magnitude, the audit tolerance it is measured against, their ratio, and whether the
audit is expected to detect it.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import geopandas as gpd  # type: ignore[import-untyped]
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

HERE = Path(__file__).parent
DEFECT_TYPES = (
    "self_intersection",
    "sliver",
    "overlap",
    "duplicate_vertex",
    "undershoot",
    "unnoded_t_junction",
)
LAYER_OF = {
    "self_intersection": "parcels",
    "sliver": "parcels",
    "overlap": "parcels",
    "duplicate_vertex": "parcels",
    "undershoot": "roads",
    "unnoded_t_junction": "roads",
}
# Types whose magnitude is swept as a ratio of the audit tolerance. The others run once:
# their checks are exact (self-intersection, duplicate vertex, unnoded T-junction) or the
# profile tolerance is 0 so no ratio exists (overlap under generic-polygon).
SWEPT = frozenset({"sliver", "undershoot"})
DEFAULT_RATIO = 0.5
OVERLAP_WIDTH = 2.0
# generic-polygon passes profile.tolerance = 0 to the overlap check: any area counts.
OVERLAP_TOLERANCE = 0.0
# jalan: no_overshoot_undershoot tolerance, also the radius _merge_road_endpoints uses to
# title an unconnected end "Possible undershoot".
UNDERSHOOT_TOLERANCE = 2.0
# TOP-SLIVER flags a polygon whose compactness 4*pi*A/P^2 is under this (fixed in the audit).
SLIVER_COMPACTNESS = 0.05
# The unnoded T-junction moves the through node this far along the street, past the
# no_dangles tolerance (0.5 m), so the stem's end no longer meets a segment end.
T_JUNCTION_SHIFT = 10.0
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


def plan(
    parcels: Sequence[BaseGeometry],
    roads: Sequence[LineString],
    per_type: int,
    seed: int,
) -> dict[str, list[Site]]:
    """Pick per_type isolated sites for every defect type, shared across types.

    A site's features and every feature touching them are excluded from later picks,
    on that layer and across types, so no two defects touch. Raises NotEnoughSites
    when the grid is too small.
    """
    rng = random.Random(seed)
    sites: dict[str, list[Site]] = {}

    order = list(range(len(parcels)))
    rng.shuffle(order)
    near = _neighbours(parcels)
    excluded: set[int] = set()
    single = [((index,), ()) for index in order]
    for label in ("self_intersection", "sliver"):
        sites[label] = _pick(single, per_type, excluded, near, "parcels", label)
    pairs = [
        ((index, east), ()) for index in order if (east := _east_of(parcels, index)) is not None
    ]
    sites["overlap"] = _pick(pairs, per_type, excluded, near, "parcels", "overlap")
    sites["duplicate_vertex"] = _pick(
        single, per_type, excluded, near, "parcels", "duplicate_vertex"
    )

    nodes = _ends(roads)
    near = _neighbours(roads)
    excluded = set()
    junctions = []
    for node in sorted(nodes):
        members = nodes[node]
        pair = _through_pair(node, members, roads) if len(members) == 3 else None
        if pair is not None:
            junctions.append((pair, (node,)))
    rng.shuffle(junctions)
    sites["unnoded_t_junction"] = _pick(
        junctions, per_type, excluded, near, "roads", "unnoded_t_junction"
    )
    crossings = [node for node in sorted(nodes) if len(nodes[node]) == 4]
    rng.shuffle(crossings)
    ends = []
    for node in crossings:
        index, end = rng.choice(nodes[node])
        ends.append(((index,), (end,)))
    sites["undershoot"] = _pick(ends, per_type, excluded, near, "roads", "undershoot")
    return sites


def apply(
    defect_type: str,
    sites: Sequence[Site],
    geometries: Sequence[BaseGeometry],
    ratio: float | None,
) -> tuple[list[BaseGeometry], list[Defect]]:
    """Return the layer with one defect per site, and the defects.

    ``ratio`` sets the magnitude of swept types as ratio x tolerance; other types ignore it.
    Feature indices stay stable; a sliver appends its strip as a new feature.
    """
    out = list(geometries)
    defects: list[Defect] = []
    layer = LAYER_OF[defect_type]
    cache: dict[str, dict[Point, list[tuple[int, int]]]] = {}

    def nodes_of(lines: Sequence[LineString]) -> dict[Point, list[tuple[int, int]]]:
        if "nodes" not in cache:
            cache["nodes"] = _ends(lines)
        return cache["nodes"]

    for features, detail in sites:
        index = features[0]
        if defect_type == "self_intersection":
            x0, y0, x1, y1 = out[index].bounds
            out[index] = Polygon([(x0, y0), (x1, y1), (x1, y0), (x0, y1)])
            defects.append(Defect(defect_type, layer, index))
        elif defect_type == "sliver":
            # Cut a strip off the donor's north edge and add it as a new feature, so
            # coverage stays gap-free and overlap-free.
            assert ratio is not None
            x0, y0, x1, y1 = out[index].bounds
            tolerance = sliver_tolerance(x1 - x0)
            width = ratio * tolerance
            out[index] = box(x0, y0, x1, y1 - width)
            out.append(box(x0, y1 - width, x1, y1))
            defects.append(
                Defect(
                    defect_type,
                    layer,
                    len(out) - 1,
                    index,
                    magnitude=width,
                    tolerance=tolerance,
                    ratio_r=ratio,
                    expected_detect=width < tolerance,
                )
            )
        elif defect_type == "overlap":
            neighbour = features[1]
            x0, y0, x1, y1 = out[index].bounds
            out[index] = box(x0, y0, x1 + OVERLAP_WIDTH, y1)
            area = OVERLAP_WIDTH * (y1 - y0)
            defects.append(
                Defect(
                    defect_type,
                    layer,
                    index,
                    neighbour,
                    magnitude=area,
                    tolerance=OVERLAP_TOLERANCE,
                    expected_detect=area > OVERLAP_TOLERANCE,
                )
            )
        elif defect_type == "duplicate_vertex":
            polygon = out[index]
            assert isinstance(polygon, Polygon)
            ring = list(polygon.exterior.coords)
            out[index] = Polygon([ring[0], *ring[:-1]])
            defects.append(Defect(defect_type, layer, index))
        elif defect_type == "unnoded_t_junction":
            # Extend the through segment a past the node and shorten b to match: a and b
            # still meet, collinear, but the stem now ends on a's interior with no vertex.
            a, b, stem = features
            node = cast(Point, detail[0])
            lines = cast(Sequence[LineString], geometries)
            ends = dict(nodes_of(lines)[node])
            far_a, far_b = _far_end(lines[a], ends[a]), _far_end(lines[b], ends[b])
            step = T_JUNCTION_SHIFT / math.dist(node, far_b)
            moved = (node[0] + (far_b[0] - node[0]) * step, node[1] + (far_b[1] - node[1]) * step)
            out[a] = LineString([far_a, moved])
            out[b] = LineString([moved, far_b])
            defects.append(Defect(defect_type, layer, stem, a))
        elif defect_type == "undershoot":
            assert ratio is not None
            end = cast(int, detail[0])
            line = out[index]
            assert isinstance(line, LineString)
            gap = ratio * UNDERSHOOT_TOLERANCE
            coords = [(float(x), float(y)) for x, y in line.coords]
            (nx, ny), (fx, fy) = coords[end], _far_end(line, end)
            length = math.hypot(fx - nx, fy - ny)
            if gap >= length:
                raise ValueError(f"undershoot gap {gap} m exceeds segment length {length} m")
            coords[end] = (nx + (fx - nx) * gap / length, ny + (fy - ny) * gap / length)
            out[index] = LineString(coords)
            defects.append(
                Defect(
                    defect_type,
                    layer,
                    index,
                    magnitude=gap,
                    tolerance=UNDERSHOOT_TOLERANCE,
                    ratio_r=ratio,
                    expected_detect=0 < gap <= UNDERSHOOT_TOLERANCE,
                )
            )
        else:
            raise ValueError(f"unknown defect type: {defect_type}")
    return out, defects


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
    for defect_type in DEFECT_TYPES:
        layer = LAYER_OF[defect_type]
        geometries, defects = apply(
            defect_type, sites[defect_type], list(frames[layer].geometry), args.ratio
        )
        path = args.out / f"{defect_type}.gpkg"
        path.unlink(missing_ok=True)
        gpd.GeoDataFrame(geometry=geometries, crs=frames[layer].crs).to_file(
            path, layer=layer, driver="GPKG"
        )
        crs = frames[layer].crs.to_string()
        rows += [truth_record(item, crs, args.seed) for item in defects]
    write_truth(args.out / "truth.csv", rows)
    print(f"Wrote {len(DEFECT_TYPES)} files and truth.csv ({len(rows)} defects) to {args.out}")


if __name__ == "__main__":
    main()
