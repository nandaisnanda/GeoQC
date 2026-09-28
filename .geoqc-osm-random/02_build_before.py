"""Turn the raw Overpass response into the BEFORE layer and inspect it with GeoQC.

Every geometry comes from OSM. Nothing is imputed: elements that cannot form a
closed ring (open ways such as roads) are dropped and counted, not patched.
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon

import geoqc
from geoqc import validate_geometry

ROOT = Path(__file__).resolve().parent
raw = json.loads((ROOT / "osm-raw.json").read_text(encoding="utf-8"))

rows: list[dict] = []
skipped_open_way = 0
skipped_too_few = 0

for element in raw["elements"]:
    geometry = element.get("geometry") or []
    coords = [(point["lon"], point["lat"]) for point in geometry]
    if len(coords) < 4:
        skipped_too_few += 1
        continue
    if coords[0] != coords[-1]:
        skipped_open_way += 1
        continue
    tags = element.get("tags", {})
    rows.append(
        {
            "osm_id": int(element["id"]),
            "osm_class": next(
                (key for key in ("building", "landuse", "natural", "leisure") if key in tags),
                "unknown",
            ),
            "osm_value": next(
                (tags[key] for key in ("building", "landuse", "natural", "leisure") if key in tags),
                "unknown",
            ),
            "name": tags.get("name", ""),
            "geometry": Polygon(coords),
        }
    )

before = gpd.GeoDataFrame(rows, crs="EPSG:4326")
before.to_file(ROOT / "before.geojson", driver="GeoJSON")

results = [validate_geometry(geom) for geom in before.geometry]
findings = [
    {
        "row": index,
        "osm_id": int(before.osm_id.iloc[index]),
        "osm_value": before.osm_value.iloc[index],
        "shapely_valid": bool(before.geometry.iloc[index].is_valid),
        "issues": [issue.issue_type.value for issue in result.issues],
        "messages": [issue.message for issue in result.issues],
    }
    for index, result in enumerate(results)
    if not result.is_valid
]

report = {
    "geoqc_version": geoqc.__version__,
    "geoqc_loaded_from": str(Path(geoqc.__file__).resolve()),
    "polygons_kept": len(before),
    "skipped_open_ways": skipped_open_way,
    "skipped_degenerate": skipped_too_few,
    "invalid_features_geoqc": len(findings),
    "invalid_features_shapely": int((~before.geometry.is_valid).sum()),
    "issue_type_counts": {
        issue: sum(finding["issues"].count(issue) for finding in findings)
        for issue in sorted({issue for finding in findings for issue in finding["issues"]})
    },
    "findings": findings,
}
(ROOT / "before-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps({key: value for key, value in report.items() if key != "findings"}, indent=2))
print(f"first findings: {json.dumps(findings[:5], indent=2)}")
