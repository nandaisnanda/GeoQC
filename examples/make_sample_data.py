"""Generate examples/sample_defects.gpkg, a tiny dataset with known QC defects.

Layers (EPSG:32748, metres):

* ``parcels``: one clean parcel, one self-intersecting "bowtie" (id 2),
  one sliver polygon 0.05 m wide (id 3), and one parcel overlapping id 1 (id 4).
* ``roads``: a rectangular network whose top segment (id 4) stops 0.5 m short
  of the right-hand road, leaving two dead ends.

Audit it with the example profiles in ``docs/examples``.

Run: ``python examples/make_sample_data.py``
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Polygon

OUTPUT = Path(__file__).with_name("sample_defects.gpkg")
CRS = "EPSG:32748"
X0, Y0 = 430_000.0, 9_140_000.0


def _poly(coords: list[tuple[float, float]]) -> Polygon:
    return Polygon([(X0 + x, Y0 + y) for x, y in coords])


def _line(coords: list[tuple[float, float]]) -> LineString:
    return LineString([(X0 + x, Y0 + y) for x, y in coords])


def main() -> None:
    parcels = gpd.GeoDataFrame(
        {
            "parcel_id": [1, 2, 3, 4],
            "defect": ["none", "self_intersection", "sliver", "overlap"],
        },
        geometry=[
            _poly([(0, 0), (50, 0), (50, 40), (0, 40)]),
            _poly([(60, 0), (100, 40), (100, 0), (60, 40)]),
            _poly([(0, 45), (35, 45), (35, 45.05), (0, 45.05)]),
            _poly([(40, 30), (70, 30), (70, 60), (40, 60)]),
        ],
        crs=CRS,
    )
    roads = gpd.GeoDataFrame(
        {
            "road_id": [1, 2, 3, 4],
            "defect": ["none", "none", "none", "disconnected"],
        },
        geometry=[
            _line([(0, -10), (100, -10)]),
            _line([(100, -10), (100, 80)]),
            _line([(0, -10), (0, 80)]),
            _line([(0, 80), (99.5, 80)]),
        ],
        crs=CRS,
    )
    OUTPUT.unlink(missing_ok=True)
    parcels.to_file(OUTPUT, layer="parcels", driver="GPKG")
    roads.to_file(OUTPUT, layer="roads", driver="GPKG")
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
