"""Write a clean synthetic parcel grid and a fully noded road grid to out/clean.gpkg.

The road grid mixes four-way crossings with interior three-way junctions, so both
undershoots (at crossings) and unnoded T-junctions (at three-way junctions) fit in it.
"""

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


def _band_columns(band: int, cells: int) -> list[float]:
    """x offsets (from the origin) of the vertical streets in one horizontal band.

    Bands come in pairs: two aligned with the block grid, then two shifted by half a
    block. Both border streets are always present, so every street end meets a road.
    """
    if (band // 2) % 2 == 0:
        return [i * BLOCK_SIZE for i in range(cells + 1)]
    half = BLOCK_SIZE / 2
    return [0.0, *(half + i * BLOCK_SIZE for i in range(cells)), cells * BLOCK_SIZE]


def road_grid(cells: int) -> list[LineString]:
    """A cells x cells street grid split at every junction, plus a cul-de-sac per corner.

    Where two bands with the same offset meet, the horizontal street has four-way
    crossings; where a shifted band meets an aligned one, it has a three-way junction
    every half block. Feature order is fixed: horizontal segments street by street,
    then vertical segments band by band, then the four cul-de-sacs.
    """
    x0, y0 = ORIGIN
    lines = []
    for street in range(cells + 1):
        columns = sorted(
            {
                *(_band_columns(street - 1, cells) if street > 0 else ()),
                *(_band_columns(street, cells) if street < cells else ()),
            }
        )
        y = y0 + street * BLOCK_SIZE
        lines += [
            LineString([(x0 + left, y), (x0 + right, y)])
            for left, right in zip(columns, columns[1:], strict=False)
        ]
    for band in range(cells):
        lines += [
            LineString([(x0 + x, y0 + band * BLOCK_SIZE), (x0 + x, y0 + (band + 1) * BLOCK_SIZE)])
            for x in _band_columns(band, cells)
        ]
    reach = CUL_DE_SAC_LENGTH / math.sqrt(2)
    for i, j in ((0, 0), (cells, 0), (0, cells), (cells, cells)):
        x, y = x0 + i * BLOCK_SIZE, y0 + j * BLOCK_SIZE
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
