"""Write a clean synthetic parcel grid and a fully noded road grid to out/clean.gpkg."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
from shapely.geometry import LineString, Polygon, box

HERE = Path(__file__).parent
CRS = "EPSG:32748"
ORIGIN = (430_000.0, 9_140_000.0)
PARCEL_SIZE = 20.0
BLOCK_SIZE = 40.0
CUL_DE_SAC_LENGTH = 12.0


def parcel_grid(count: int) -> list[Polygon]:
    """Square parcels, row-major, sharing edges exactly: no gaps, no overlaps."""
    cols = math.ceil(math.sqrt(count))
    x0, y0 = ORIGIN
    return [
        box(
            x0 + (i % cols) * PARCEL_SIZE,
            y0 + (i // cols) * PARCEL_SIZE,
            x0 + (i % cols + 1) * PARCEL_SIZE,
            y0 + (i // cols + 1) * PARCEL_SIZE,
        )
        for i in range(count)
    ]


def road_grid(cells: int) -> list[LineString]:
    """A cells x cells street grid split at every junction, plus a cul-de-sac per corner.

    Feature order is fixed: horizontal segments row by row, then vertical segments
    column by column, then the four cul-de-sacs.
    """
    x0, y0 = ORIGIN

    def node(i: int, j: int) -> tuple[float, float]:
        return (x0 + i * BLOCK_SIZE, y0 + j * BLOCK_SIZE)

    lines = [
        LineString([node(i, j), node(i + 1, j)]) for j in range(cells + 1) for i in range(cells)
    ]
    lines += [
        LineString([node(i, j), node(i, j + 1)]) for i in range(cells + 1) for j in range(cells)
    ]
    reach = CUL_DE_SAC_LENGTH / math.sqrt(2)
    for i, j in ((0, 0), (cells, 0), (0, cells), (cells, cells)):
        x, y = node(i, j)
        dx = reach if i else -reach
        dy = reach if j else -reach
        lines.append(LineString([(x, y), (x + dx, y + dy)]))
    return lines


def build(parcels: int, road_cells: int) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    parcel_frame = gpd.GeoDataFrame(
        {"parcel_id": range(parcels)}, geometry=parcel_grid(parcels), crs=CRS
    )
    roads = road_grid(road_cells)
    road_frame = gpd.GeoDataFrame({"road_id": range(len(roads))}, geometry=roads, crs=CRS)
    return parcel_frame, road_frame


def write(path: Path, parcels: gpd.GeoDataFrame, roads: gpd.GeoDataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    parcels.to_file(path, layer="parcels", driver="GPKG")
    roads.to_file(path, layer="roads", driver="GPKG")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parcels", type=int, default=400)
    parser.add_argument("--road-cells", type=int, default=10)
    parser.add_argument("--out", type=Path, default=HERE / "out" / "clean.gpkg")
    args = parser.parse_args()
    write(args.out, *build(args.parcels, args.road_cells))
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
