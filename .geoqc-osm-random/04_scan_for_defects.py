"""Scan random OSM tiles for genuinely defective geometry (no injection).

Each tile is fetched from Overpass and validated with GeoQC. Nothing is
modified; the script only reports where real defects exist.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon

from geoqc import validate_geometry

ROOT = Path(__file__).resolve().parent
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Areas with large bulk building imports / rapid mapping, where geometry
# defects genuinely survive in the database.
CANDIDATES = [
    ("Jakarta, Indonesia", -6.2088, 106.8456),
    ("Lagos, Nigeria", 6.5244, 3.3792),
    ("Dhaka, Bangladesh", 23.8103, 90.4125),
    ("Cairo, Egypt", 30.0444, 31.2357),
    ("Manila, Philippines", 14.5995, 120.9842),
    ("Nairobi, Kenya", -1.2864, 36.8172),
    ("Karachi, Pakistan", 24.8607, 67.0011),
    ("Kinshasa, DR Congo", -4.4419, 15.2663),
    ("Lima, Peru", -12.0464, -77.0428),
    ("Ho Chi Minh City, Vietnam", 10.7626, 106.6602),
    ("Sao Paulo, Brazil", -23.5505, -46.6333),
    ("Mexico City, Mexico", 19.4326, -99.1332),
]


def fetch(bbox: tuple[float, float, float, float]) -> dict | None:
    query = (
        f"[out:json][timeout:60];"
        f'(way["building"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});'
        f'way["landuse"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});'
        f'way["natural"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}););'
        f"out geom;"
    )
    payload = urllib.parse.urlencode({"data": query}).encode("utf-8")
    for endpoint in ENDPOINTS:
        try:
            request = urllib.request.Request(
                endpoint,
                data=payload,
                headers={"User-Agent": "GeoQC-smoke-test/0.1.0 (local evaluation)"},
            )
            with urllib.request.urlopen(request, timeout=110) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(3)
    return None


def to_frame(raw: dict) -> gpd.GeoDataFrame:
    rows = []
    for element in raw.get("elements", []):
        coords = [(point["lon"], point["lat"]) for point in element.get("geometry") or []]
        if len(coords) < 4 or coords[0] != coords[-1]:
            continue
        tags = element.get("tags", {})
        key = next((k for k in ("building", "landuse", "natural") if k in tags), "unknown")
        rows.append(
            {
                "osm_id": int(element["id"]),
                "osm_class": key,
                "osm_value": tags.get(key, "unknown"),
                "name": tags.get("name", ""),
                "geometry": Polygon(coords),
            }
        )
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


seed = random.SystemRandom().randrange(2**32)
rng = random.Random(seed)
order = rng.sample(CANDIDATES, len(CANDIDATES))
log: list[dict] = []

for city, lat0, lon0 in order:
    lat = lat0 + rng.uniform(-0.02, 0.02)
    lon = lon0 + rng.uniform(-0.02, 0.02)
    half = 0.0075
    bbox = (round(lat - half, 6), round(lon - half, 6), round(lat + half, 6), round(lon + half, 6))
    raw = fetch(bbox)
    if raw is None:
        log.append({"city": city, "bbox": list(bbox), "status": "fetch_failed"})
        print(f"{city}: fetch failed")
        continue
    frame = to_frame(raw)
    if frame.empty:
        log.append({"city": city, "bbox": list(bbox), "status": "empty", "polygons": 0})
        print(f"{city}: no closed polygons")
        continue
    results = [validate_geometry(geom) for geom in frame.geometry]
    bad = [index for index, result in enumerate(results) if not result.is_valid]
    issue_counts: dict[str, int] = {}
    for index in bad:
        for issue in results[index].issues:
            issue_counts[issue.issue_type.value] = issue_counts.get(issue.issue_type.value, 0) + 1
    entry = {
        "city": city,
        "bbox": list(bbox),
        "status": "ok",
        "polygons": len(frame),
        "invalid_features": len(bad),
        "issue_counts": issue_counts,
    }
    log.append(entry)
    print(f"{city}: polygons={len(frame)} invalid={len(bad)} {issue_counts}")
    if bad:
        frame.to_file(ROOT / "candidate-before.geojson", driver="GeoJSON")
        (ROOT / "candidate-draw.json").write_text(
            json.dumps({"seed": seed, **entry}, indent=2), encoding="utf-8"
        )
        print(f"--> saved candidate tile with real defects: {city}")
        break
    time.sleep(2)

(ROOT / "scan-log.json").write_text(
    json.dumps({"seed": seed, "tiles": log}, indent=2), encoding="utf-8"
)
