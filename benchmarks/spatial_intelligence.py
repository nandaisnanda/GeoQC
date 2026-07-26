"""Reproducible synthetic benchmark for spatial intelligence engines."""

import argparse
import time
from collections.abc import Callable

from shapely.geometry import LineString, Polygon, box

import geoqc
from geoqc import BoundarySnapConfig, RoadNetworkConfig, SmallPolygonConfig


def measure(name: str, count: int, operation: Callable[[], object]) -> None:
    started = time.perf_counter()
    operation()
    elapsed = time.perf_counter() - started
    print(f"{name:24} features={count:7d} time={elapsed:8.3f}s rate={count / elapsed:10.0f}/s")


def polygons(count: int) -> list[Polygon]:
    return [box(index * 1.001, 0, index * 1.001 + 1, 1) for index in range(count)]


def roads(count: int) -> list[LineString]:
    return [LineString([(index * 1.001, 0), (index * 1.001 + 1, 0)]) for index in range(count)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=int, default=5_000)
    args = parser.parse_args()
    polygon_data = polygons(args.features)
    road_data = roads(args.features)
    measure(
        "smart-boundary-snap",
        args.features,
        lambda: geoqc.snap_boundaries(
            polygon_data, BoundarySnapConfig(tolerance=0.002, max_relative_area_change=0.01)
        ),
    )
    measure(
        "road-network-analyzer",
        args.features,
        lambda: geoqc.analyze_road_network(
            road_data, RoadNetworkConfig(connection_tolerance=0.002)
        ),
    )
    measure(
        "small-polygon-intel",
        args.features,
        lambda: geoqc.analyze_small_polygons(
            polygon_data,
            SmallPolygonConfig(
                sliver_area_threshold=1.1,
                tiny_island_area_threshold=0.5,
                noise_area_threshold=0.01,
                merge_tolerance=0.002,
            ),
        ),
    )


if __name__ == "__main__":
    main()
