"""Fetch a RANDOM real OpenStreetMap tile via the Overpass API.

No data is invented: whatever Overpass returns is written to disk verbatim.
The random draw is recorded (seed + chosen city + bbox) so the run is auditable.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Candidate city centres for the random draw (lat, lon).
CITIES = [
    ("Yogyakarta, Indonesia", -7.7956, 110.3695),
    ("Lisbon, Portugal", 38.7223, -9.1393),
    ("Prague, Czechia", 50.0755, 14.4378),
    ("Kyoto, Japan", 35.0116, 135.7681),
    ("Quito, Ecuador", -0.1807, -78.4678),
    ("Marrakesh, Morocco", 31.6295, -7.9811),
    ("Reykjavik, Iceland", 64.1466, -21.9426),
    ("Hanoi, Vietnam", 21.0278, 105.8342),
    ("Valparaiso, Chile", -33.0472, -71.6127),
    ("Tallinn, Estonia", 59.4370, 24.7536),
    ("Ljubljana, Slovenia", 46.0569, 14.5058),
    ("Bergen, Norway", 60.3913, 5.3221),
]

seed = random.SystemRandom().randrange(2**32)
rng = random.Random(seed)
city, lat0, lon0 = rng.choice(CITIES)

# Random jitter of up to ~1 km around the centre, then a ~1.4 km x 1.4 km box.
lat = lat0 + rng.uniform(-0.009, 0.009)
lon = lon0 + rng.uniform(-0.009, 0.009)
half = 0.0065
bbox = (round(lat - half, 6), round(lon - half, 6), round(lat + half, 6), round(lon + half, 6))

query = f"""
[out:json][timeout:90];
(
  way["building"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
  way["landuse"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
  way["natural"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
  way["leisure"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
);
out geom;
""".strip()

payload = urllib.parse.urlencode({"data": query}).encode("utf-8")
last_error: Exception | None = None
raw: dict | None = None
for endpoint in ENDPOINTS:
    for attempt in range(3):
        try:
            request = urllib.request.Request(
                endpoint,
                data=payload,
                headers={"User-Agent": "GeoQC-smoke-test/0.1.0 (local evaluation)"},
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = json.loads(response.read().decode("utf-8"))
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            time.sleep(4 * (attempt + 1))
    if raw is not None:
        break

if raw is None:
    raise SystemExit(f"Overpass fetch failed, no data written: {last_error!r}")

(ROOT / "osm-raw.json").write_text(json.dumps(raw), encoding="utf-8")
(ROOT / "draw.json").write_text(
    json.dumps(
        {
            "seed": seed,
            "city": city,
            "center": [lat, lon],
            "bbox_south_west_north_east": list(bbox),
            "overpass_query": query,
            "element_count": len(raw.get("elements", [])),
        },
        indent=2,
    ),
    encoding="utf-8",
)

print(f"seed={seed}")
print(f"city={city}")
print(f"bbox={bbox}")
print(f"elements={len(raw.get('elements', []))}")
