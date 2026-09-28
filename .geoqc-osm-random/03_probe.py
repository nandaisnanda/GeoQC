"""Probe the real OSM tile with every GeoQC analyzer, in a projected CRS."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd

from geoqc import (
    analyze_small_polygons,
    detect_spatial_duplicates,
    repair_geometries,
    validate_geometry,
)

ROOT = Path(__file__).resolve().parent
PROJECTED = "EPSG:3057"  # ISN93 / Lambert 1993 — metres, correct for Iceland

before = gpd.read_file(ROOT / "before.geojson").to_crs(PROJECTED)
buildings = before[before.osm_class == "building"].reset_index(drop=True)
print(f"total={len(before)} buildings={len(buildings)}")
print(before.osm_class.value_counts().to_dict())

geoms = list(buildings.geometry)

validation = [validate_geometry(geom) for geom in geoms]
print(f"geometry issues (buildings): {sum(len(r.issues) for r in validation)}")

duplicates = detect_spatial_duplicates(geoms)
print(f"duplicate report fields: {[f for f in dir(duplicates) if not f.startswith('_')]}")
print(f"duplicate pairs: {len(duplicates.duplicates)}")

small = analyze_small_polygons(geoms)
print(f"small report fields: {[f for f in dir(small) if not f.startswith('_')]}")

coverage = repair_geometries(geoms)
print(f"coverage fields: {[f for f in dir(coverage) if not f.startswith('_')]}")
print(f"coverage actions: {len(coverage.actions) if hasattr(coverage, 'actions') else 'n/a'}")
summary = {}
for field in dir(coverage):
    if field.startswith("_"):
        continue
    value = getattr(coverage, field)
    if isinstance(value, (int, float, str, bool)):
        summary[field] = value
print(json.dumps(summary, indent=2, default=str))
