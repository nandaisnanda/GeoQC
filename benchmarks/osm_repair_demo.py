"""Run a reproducible GeoQC repair demo against OSM buildings in Menteng.

Buildings are downloaded from a 2 km x 2 km sample window, then a controlled
self-intersection is introduced into one random feature so repair is exercised.
Outputs include before/after Shapefiles, JPG maps, and a JSON audit report.
"""

from __future__ import annotations

import argparse
import json
import random
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib.pyplot as plt
import pyogrio
import shapely
from pyproj import Transformer
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry

from geoqc.application.services.topology_repair import RepairSession
from geoqc.domain.models.topology_repair import RepairConfig
from geoqc.infrastructure.gis.shapely_topology_repairer import ShapelyTopologyRepairer

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
MENTENG_CENTRE = (-6.1944, 106.8294)
SAMPLE_SIDE_METRES = 2_000.0


def _sample_bounds() -> tuple[Polygon, tuple[float, float, float, float]]:
    """Build an exact 4 km² window in Jakarta's local UTM CRS."""
    latitude, longitude = MENTENG_CENTRE
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32748", always_xy=True)
    to_wgs84 = Transformer.from_crs("EPSG:32748", "EPSG:4326", always_xy=True)
    centre_x, centre_y = to_utm.transform(longitude, latitude)
    half = SAMPLE_SIDE_METRES / 2
    west, south = to_wgs84.transform(centre_x - half, centre_y - half)
    east, north = to_wgs84.transform(centre_x + half, centre_y + half)
    return box(west, south, east, north), (south, west, north, east)


def _fetch_buildings() -> tuple[list[dict[str, Any]], Polygon]:
    sample_window, (south, west, north, east) = _sample_bounds()
    query = f"""
    [out:json][timeout:90];
    way[building]({south},{west},{north},{east});
    out tags geom;
    """
    request = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": "GeoQC-OSM-repair-demo/0.1"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.load(response)
    candidates: list[dict[str, Any]] = []
    for element in payload.get("elements", []):
        coordinates = [(node["lon"], node["lat"]) for node in element.get("geometry", [])]
        if len(coordinates) < 4:
            continue
        if coordinates[0] != coordinates[-1]:
            coordinates.append(coordinates[0])
        geometry = Polygon(coordinates).intersection(sample_window)
        if geometry.geom_type == "Polygon" and geometry.is_valid and geometry.area > 0:
            candidates.append({**element, "shape": geometry})
    if not candidates:
        raise RuntimeError("No OSM building polygons returned for the Menteng sample window.")
    return candidates, sample_window


def _make_bowtie(source: Polygon) -> Polygon:
    """Create a visible self-intersection inside the source bounding box."""
    min_x, min_y, max_x, max_y = source.bounds
    pad_x = (max_x - min_x) * 0.08
    pad_y = (max_y - min_y) * 0.08
    return Polygon(
        [
            (min_x + pad_x, min_y + pad_y),
            (max_x - pad_x, max_y - pad_y),
            (max_x - pad_x, min_y + pad_y),
            (min_x + pad_x, max_y - pad_y),
            (min_x + pad_x, min_y + pad_y),
        ]
    )


def _write_map(
    frame: gpd.GeoDataFrame, sample_window: Polygon, path: Path, title: str, color: str
) -> None:
    figure, axis = plt.subplots(figsize=(8, 8), dpi=160)
    frame.plot(ax=axis, facecolor="#cbd5e1", edgecolor="#64748b", linewidth=0.35, alpha=0.85)
    frame.loc[frame["selected"]].plot(
        ax=axis, facecolor=color, edgecolor="#172033", linewidth=1.8, alpha=0.95
    )
    min_x, min_y, max_x, max_y = sample_window.bounds
    axis.set_xlim(min_x, max_x)
    axis.set_ylim(min_y, max_y)
    axis.set_aspect("equal")
    axis.set_title(title, fontsize=14, fontweight="bold")
    axis.set_xlabel("Longitude (EPSG:4326)")
    axis.set_ylabel("Latitude (EPSG:4326)")
    axis.grid(alpha=0.25)
    figure.tight_layout()
    figure.savefig(path, format="jpg", pil_kwargs={"quality": 94})
    plt.close(figure)


def run(seed: int, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates, sample_window = _fetch_buildings()
    selected = random.Random(seed).choice(candidates)
    source: Polygon = selected["shape"]
    selected_index = candidates.index(selected)
    before_geometries: list[BaseGeometry] = [candidate["shape"] for candidate in candidates]
    before_geometries[selected_index] = _make_bowtie(source)

    session = RepairSession(
        [shapely.to_wkt(geometry) for geometry in before_geometries],
        ShapelyTopologyRepairer(),
        RepairConfig(remove_slivers=False, resolve_overlaps=False, fill_gaps=False),
    )
    result = session.apply()
    after_geometries = [shapely.from_wkt(value) for value in result.after_wkt]
    before = before_geometries[selected_index]
    after = after_geometries[selected_index]
    item = result.report.results[selected_index].result
    records = [
        {
            "osm_id": int(candidate["id"]),
            "building": str(candidate.get("tags", {}).get("building", "yes")),
            "selected": index == selected_index,
            "valid": bool(geometry.is_valid),
            "status": status,
        }
        for index, (candidate, geometry, status) in enumerate(
            zip(candidates, before_geometries, ["before"] * len(candidates), strict=True)
        )
    ]
    before_frame = gpd.GeoDataFrame(
        records,
        geometry=before_geometries,
        crs="EPSG:4326",
    )
    after_records = [
        {**record, "valid": bool(geometry.is_valid), "status": repair.result.status.value}
        for record, geometry, repair in zip(
            records, after_geometries, result.report.results, strict=True
        )
    ]
    after_frame = gpd.GeoDataFrame(
        after_records,
        geometry=after_geometries,
        crs="EPSG:4326",
    )
    pyogrio.write_dataframe(before_frame, output_dir / "osm_before.shp", driver="ESRI Shapefile")
    pyogrio.write_dataframe(after_frame, output_dir / "osm_after.shp", driver="ESRI Shapefile")
    _write_map(before_frame, sample_window, output_dir / "osm_before.jpg", "MENTENG 4 km² — BEFORE", "#ef4444")
    _write_map(after_frame, sample_window, output_dir / "osm_after.jpg", "MENTENG 4 km² — AFTER GeoQC", "#22c55e")

    report = {
        "source": {
            "area_name": "Menteng, Jakarta Pusat",
            "sample_area_km2": 4.0,
            "sample_side_metres": SAMPLE_SIDE_METRES,
            "building_count": len(candidates),
            "selected_osm_id": int(selected["id"]),
            "seed": seed,
            "scenario": "controlled_self_intersection_in_random_osm_building",
            "osm_url": f"https://www.openstreetmap.org/{selected['type']}/{selected['id']}",
            "original_osm_geometry_valid": bool(source.is_valid),
        },
        "test": result.report.to_dict(),
        "validation": {
            "before_valid": bool(before.is_valid),
            "before_reason": str(shapely.is_valid_reason(before)),
            "after_valid": bool(after.is_valid),
            "after_reason": str(shapely.is_valid_reason(after)),
        },
        "outputs": sorted(path.name for path in output_dir.iterdir()),
    }
    (output_dir / "repair_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260726)
    parser.add_argument("--output", type=Path, default=Path("artifacts/osm_repair_demo"))
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.seed, arguments.output), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()