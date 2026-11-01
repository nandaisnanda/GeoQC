"""Copy out/clean.gpkg to out/defects.gpkg with known defects, listed in out/truth.csv."""

from __future__ import annotations

import argparse
import csv
import random
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
from make_clean import write
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.base import BaseGeometry

HERE = Path(__file__).parent
DEFECT_TYPES = (
    "self_intersection",
    "sliver",
    "overlap",
    "duplicate_vertex",
    "undershoot",
    "unnoded_t_junction",
)
OVERLAP_WIDTH = 2.0
SLIVER_WIDTH = 0.1
UNDERSHOOT_GAP = (0.5, 1.5)

Point = tuple[float, float]


@dataclass(frozen=True)
class Defect:
    """One injected defect. related_index is the other feature it touches, or -1."""

    defect_type: str
    layer: str
    feature_index: int
    related_index: int = -1
    detail: str = ""


def _take(pool: Iterator[int], fits: Callable[[int], bool], count: int, label: str) -> list[int]:
    chosen = [index for index in pool if fits(index)][:count]
    if len(chosen) < count:
        raise ValueError(f"only {len(chosen)} free features for {label}, need {count}")
    return chosen


def inject_parcels(
    geometries: list[BaseGeometry], per_type: int, rng: random.Random
) -> tuple[list[BaseGeometry], list[Defect]]:
    """Bowtie, sliver, overlap and duplicate vertex, each on its own parcel."""
    out = list(geometries)
    order = list(range(len(out)))
    rng.shuffle(order)
    used: set[int] = set()
    defects: list[Defect] = []

    def east_of(index: int) -> int | None:
        _, y0, x1, _ = out[index].bounds
        nxt = index + 1
        if nxt < len(geometries) and out[nxt].bounds[0] == x1 and out[nxt].bounds[1] == y0:
            return nxt
        return None

    def free(index: int) -> bool:
        return index not in used

    for index in _take(iter(order), free, per_type, "self_intersection"):
        x0, y0, x1, y1 = out[index].bounds
        out[index] = Polygon([(x0, y0), (x1, y1), (x1, y0), (x0, y1)])
        used.add(index)
        defects.append(Defect("self_intersection", "parcels", index))

    for index in _take(iter(order), free, per_type, "sliver"):
        # Cut a thin strip off the donor's north edge and add it as a new feature,
        # so coverage stays gap-free and overlap-free.
        x0, y0, x1, y1 = out[index].bounds
        out[index] = box(x0, y0, x1, y1 - SLIVER_WIDTH)
        out.append(box(x0, y1 - SLIVER_WIDTH, x1, y1))
        used.add(index)
        defects.append(Defect("sliver", "parcels", len(out) - 1, index))

    def overlap_fits(index: int) -> bool:
        neighbour = east_of(index)
        return free(index) and neighbour is not None and free(neighbour)

    for index in _take(iter(order), overlap_fits, per_type, "overlap"):
        neighbour = east_of(index)
        assert neighbour is not None
        x0, y0, x1, y1 = out[index].bounds
        out[index] = box(x0, y0, x1 + OVERLAP_WIDTH, y1)
        used.update((index, neighbour))
        defects.append(Defect("overlap", "parcels", index, neighbour))

    for index in _take(iter(order), free, per_type, "duplicate_vertex"):
        polygon = out[index]
        assert isinstance(polygon, Polygon)
        ring = list(polygon.exterior.coords)
        out[index] = Polygon([ring[0], *ring[:-1]])
        used.add(index)
        defects.append(Defect("duplicate_vertex", "parcels", index))
    return out, defects


def _key(point: Point) -> Point:
    return (round(point[0], 6), round(point[1], 6))


def _ends(lines: list[LineString]) -> dict[Point, list[tuple[int, int]]]:
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
    node: Point, members: list[tuple[int, int]], lines: list[LineString]
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


def inject_roads(
    lines: list[LineString], per_type: int, rng: random.Random
) -> tuple[list[LineString], list[Defect]]:
    """Unnoded T-junctions on degree-3 nodes, then undershoots on degree-4 nodes."""
    out: list[LineString | None] = list(lines)
    nodes = _ends(lines)
    used: set[int] = set()
    # (kept line, removed line, stem) per T-junction, applied after index remapping.
    junctions: list[tuple[int, int, int]] = []

    # Greedy in coordinate order picks every other node along a street, which is the
    # largest set where no two T-junctions share a feature.
    slots: list[tuple[Point, int, int, int]] = []
    for node in sorted(nodes):
        members = nodes[node]
        pair = _through_pair(node, members, lines) if len(members) == 3 else None
        if pair is None or used.intersection(pair):
            continue
        used.update(pair)
        slots.append((node, *pair))
    if len(slots) < per_type:
        raise ValueError(f"only {len(slots)} T-junction slots, need {per_type}")
    used = set()
    for node, a, b, stem in rng.sample(slots, per_type):
        end_of = dict(nodes[node])
        start, finish = _far_end(lines[a], end_of[a]), _far_end(lines[b], end_of[b])
        # One straight line through the node with no vertex there: the stem now ends
        # on the middle of a segment instead of at a shared node.
        out[a] = LineString([start, finish])
        out[b] = None
        used.update((a, b, stem))
        junctions.append((a, b, stem))

    crossings = [node for node in sorted(nodes) if len(nodes[node]) == 4]
    rng.shuffle(crossings)
    undershoots: list[tuple[int, float]] = []
    for node in crossings:
        if len(undershoots) == per_type:
            break
        candidates = [(index, end) for index, end in nodes[node] if index not in used]
        if not candidates:
            continue
        index, end = rng.choice(candidates)
        gap = rng.uniform(*UNDERSHOOT_GAP)
        line = out[index]
        assert line is not None
        coords = list(line.coords)
        (nx, ny), (fx, fy) = coords[end], _far_end(line, end)
        length = ((fx - nx) ** 2 + (fy - ny) ** 2) ** 0.5
        coords[end] = (nx + (fx - nx) * gap / length, ny + (fy - ny) * gap / length)
        out[index] = LineString(coords)
        used.add(index)
        undershoots.append((index, gap))
    if len(undershoots) < per_type:
        raise ValueError(f"only {len(undershoots)} undershoot slots, need {per_type}")

    remap: dict[int, int] = {}
    kept: list[LineString] = []
    for index, line in enumerate(out):
        if line is not None:
            remap[index] = len(kept)
            kept.append(line)
    defects = [
        Defect("unnoded_t_junction", "roads", remap[stem], remap[a]) for a, _, stem in junctions
    ]
    defects += [
        Defect("undershoot", "roads", remap[index], detail=f"gap_m={gap:.3f}")
        for index, gap in undershoots
    ]
    return kept, defects


def inject(
    parcels: gpd.GeoDataFrame, roads: gpd.GeoDataFrame, per_type: int, seed: int
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, list[Defect]]:
    rng = random.Random(seed)
    parcel_geoms, parcel_defects = inject_parcels(list(parcels.geometry), per_type, rng)
    road_geoms, road_defects = inject_roads(list(roads.geometry), per_type, rng)
    parcel_frame = gpd.GeoDataFrame(geometry=parcel_geoms, crs=parcels.crs)
    road_frame = gpd.GeoDataFrame(geometry=road_geoms, crs=roads.crs)
    return parcel_frame, road_frame, [*parcel_defects, *road_defects]


def write_truth(path: Path, defects: list[Defect]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["defect_type", "layer", "feature_index", "related_index", "detail"])
        for item in defects:
            writer.writerow(
                [item.defect_type, item.layer, item.feature_index, item.related_index, item.detail]
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", type=Path, default=HERE / "out" / "clean.gpkg")
    parser.add_argument("--out", type=Path, default=HERE / "out" / "defects.gpkg")
    parser.add_argument("--truth", type=Path, default=HERE / "out" / "truth.csv")
    parser.add_argument("--per-type", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    parcels = gpd.read_file(args.clean, layer="parcels")
    roads = gpd.read_file(args.clean, layer="roads")
    parcel_frame, road_frame, defects = inject(parcels, roads, args.per_type, args.seed)
    write(args.out, parcel_frame, road_frame)
    write_truth(args.truth, defects)
    print(f"Wrote {args.out} and {args.truth} ({len(defects)} defects)")


if __name__ == "__main__":
    main()
