# GeoQC

[![PyPI](https://img.shields.io/pypi/v/geoqc.svg?color=brightgreen&cacheSeconds=300&v=0.2.0)](https://pypi.org/project/geoqc/)
[![Python versions](https://img.shields.io/pypi/pyversions/geoqc.svg?color=brightgreen&cacheSeconds=300&v=0.2.0)](https://pypi.org/project/geoqc/)
[![License: MIT](https://img.shields.io/badge/License-MIT-brightgreen.svg?v=0.2.0)](LICENSE)

**GeoQC** is a typed Python toolkit for quality control of geospatial data. It
detects common geometry defects and provides reusable building blocks for CRS,
datum, axis-order, attribute, batch, and reporting workflows.

> **Release status:** `0.2.0` (alpha). The top-level `validate_geometry()` API is
> ready for evaluation. Advanced APIs may evolve before `1.0` and changes will
> be documented in the changelog.

## Two ways to use GeoQC

GeoQC exposes one validation engine through several surfaces, so results are
identical no matter how you call it:

1. **Developers** install the package (`pip install geoqc`) and use the
   [Python API](#quick-start) or the [`geoqc` CLI](docs/cli.md).
2. **Everyone else** runs the bundled web app (`apps/web`) in a browser. It
   uploads datasets to the FastAPI backend, which validates them with the
   **same `geoqc` engine** — no validation logic is reimplemented in
   JavaScript. See [API and deployment](docs/api.md) to run the backend and
   client locally.

Because the web API, CLI, and Python API all call
`ShapelyGeometryValidator` through the same audit engine, the Website, CLI, and
library always agree on what is valid. See [Architecture](docs/architecture.md).

## Features

- Validate Shapely geometries for empty or invalid values, self-intersections,
  ring errors, and duplicate vertices.
- Repair topology with minimal shape change — self-intersections, invalid rings,
  duplicate vertices, slivers, overlaps, and enclosed gaps — with before/after
  geometry, a repair report, and preview/apply/undo. See
  [intelligent topology repair](docs/topology-repair.md).
- Read common vector datasets through GeoPandas and Pyogrio, including
  Shapefile, GeoJSON, GeoPackage, and FlatGeobuf.
- Analyze and repair road networks, including every `MultiLineString` part,
  dangling/broken connections, duplicate segments, unnoded intersections,
  conservative endpoint snapping, full intersection noding, minimum connector
  planning for disconnected islands, and source-feature provenance. The
  `geoqc repair-roads` CLI writes a new GeoPackage atomically.
- Apply declarative Phase-2 topology checks for matching boundaries, connected
  endpoints, overshoot/undershoot, geometry types, multipart features, spikes,
  minimum segment/vertex spacing, spatial relations, attribute-controlled
  overlap, and precision grids.
- Stream GeoPackage, Shapefile, GeoJSON, and GeoParquet audits in bounded
  Arrow chunks without loading the complete dataset into RAM.
- Audit independent datasets concurrently with memory-aware process scheduling,
  isolated failures, and deterministic output ordering.
- Inspect CRS consistency, axis order, and possible datum shifts.
- Run typed, extensible quality rules with immutable result models.
- Process bounded batches and generate optional HTML or interactive reports.
- Expose a hardened FastAPI upload endpoint and a responsive React client.

GeoQC can return repaired geometries or write a new output dataset, but it
never silently modifies a source dataset. Ambiguous repairs are marked for
review and retain before/after geometry plus change metrics.

## Requirements

- Python 3.12 or 3.13
- A platform supported by GeoPandas, Pyogrio, Shapely, and PyProj wheels

## Installation

Install the core library and CLI from PyPI:

```bash
python -m pip install geoqc
```

Install optional delivery and reporting dependencies only when needed:

```bash
python -m pip install "geoqc[api]"       # FastAPI and Uvicorn
python -m pip install "geoqc[report]"    # Jinja2 and Folium
python -m pip install "geoqc[all]"       # All optional features
```

To install a source checkout:

```bash
python -m pip install .
```

## Quick start

### Audit a dataset in Python

The repository ships a 120 KB sample, `examples/sample_defects.gpkg`, with
known defects: a self-intersecting parcel, a 0.05 m sliver, two overlapping
parcels, and a road that stops 0.5 m short of the network. From a source
checkout:

```python
import geoqc

report = geoqc.audit_dataset(
    "examples/sample_defects.gpkg",
    layer="parcels",
    profile="docs/examples/parcel-profile.yaml",
)
print(report.status, report.issue_count)
for issue in report.issues:
    print(issue.code, issue.feature_index, issue.message)
```

Expected output includes `GEO-SELF_INTERSECTION`, `TOP-MINIMUM-AREA` for the
sliver, and `TOP-NO-OVERLAP`. Use `layer="roads"` with
`docs/examples/road-network-profile.yaml` to see the two `ROAD-DEAD_END`
findings. `examples/make_sample_data.py` regenerates the file.

The report always includes dataset metadata and explicit `passed`, `failed`,
`error`, or `skipped` outcomes. Attribute checks require an `AttributeSchema`;
unconfigured topology/spatial checks and checks lacking a safe CRS are skipped
with an actionable reason.

For profile-driven rules and issue-layer output, load a reusable profile:

```python
from geoqc import audit_file, load_quality_profile, write_issue_layers

profile = load_quality_profile("parcel-profile.yaml")
result = audit_file("parcels.gpkg", layer="parcels", profile=profile)

print(result.quality_score)
print(result.issues[0].recommendation)
write_issue_layers(result, "parcel-issues.gpkg")
```

Presets are available for parcels, administrative boundaries, roads, and
point surveys. Findings include severity, repair risk, source feature indexes,
suggested fixes, and issue geometry. See the
[dataset quality workflow](docs/quality-workflow.md) for custom cross-layer
rules, safe repair, reports, CRS/unit guards, and CI quality gates.

### Validate one geometry

Validate one Shapely geometry using the stable top-level API:

```python
from shapely.geometry import Polygon

from geoqc import GeometryIssueType, validate_geometry

polygon = Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])
result = validate_geometry(polygon)

print(result.is_valid)  # False
for issue in result.issues:
    print(issue.issue_type, issue.message)

if result.has_issue(GeometryIssueType.SELF_INTERSECTION):
    print("Repair the polygon before using it downstream.")
```

Results are immutable, typed dataclasses. Passing an object that is not a
Shapely geometry raises `TypeError` so contract errors are detected early.

## Indonesian presets

Ready-made profiles check geometry and topology only. They require no
attribute columns, because each agency uses its own schema. They ship inside the
package, so a pip install has them. List them with `geoqc presets` and run one
by name:

```bash
geoqc check persil.gpkg --preset bidang-tanah
```

The same files are in [docs/examples/](docs/examples/) for reference.

| Preset | Layer name | Checks |
| --- | --- | --- |
| `batas-administrasi` | `batas_administrasi` | overlaps, gaps, spikes, slivers |
| `bidang-tanah` | `bidang_tanah` | overlaps, spikes, tiny parcels, near-duplicate vertices |
| `kawasan-hutan` | `kawasan_hutan` | overlaps, spikes, slivers |
| `jalan` | `jalan` | multipart lines, dangles, overshoots/undershoots, short segments |
| `konsesi-kawasan-hutan` | `konsesi` + `kawasan_hutan` | concessions that intersect kawasan hutan |

Rules apply to the layer named in each file (for a single-layer file, its
file name), so rename `layer` in a copy if yours differs. Thresholds are in metres and need a projected CRS such as UTM or TM-3.

```python
import geopandas as gpd
import geoqc

result = geoqc.audit_dataset(
    "persil.gpkg", layer="bidang_tanah", profile="docs/examples/bidang-tanah.yaml"
)

profile = geoqc.load_quality_profile("docs/examples/konsesi-kawasan-hutan.yaml")
frames = {
    "konsesi": gpd.read_file("konsesi.gpkg"),
    "kawasan_hutan": gpd.read_file("kawasan_hutan.gpkg"),
}
result = geoqc.audit_layers(frames, profile=profile)
```

The cross-layer rule (`must_not_intersect`) also reports concessions that only
share an edge with kawasan hutan.

## Command-line interface

Check a dataset with no options. GeoQC picks a preset from the geometry type,
writes an issue layer and an HTML report to `geoqc_output/`, and prints a
verdict:

```bash
geoqc check data.shp
geoqc fix data.shp fixed.gpkg
```

More commands:

```bash
geoqc --help
geoqc --version
geoqc presets
geoqc audit path/to/folder
geoqc check parcels.gpkg --preset parcel --issues issues.gpkg --report report.html
geoqc repair-roads roads.shp repaired.gpkg --snap-tolerance 0.1
```

Worker count is selected automatically; use `--workers N` as a safe upper bound.
Each dataset line includes the unified report status and issue count. Folder
discovery, `--recursive`, multiprocessing, engine selection, and exit codes are
unchanged.
See [parallel streaming audits](docs/parallel-streaming.md) and the
[CLI documentation](docs/cli.md) for behavior and limitations.

## Optional API and web client

After installing the `api` extra, start the local API:

```bash
python -m uvicorn geoqc.interfaces.api.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for OpenAPI documentation. The
`POST /api/geometry/validate` endpoint accepts bounded Shapefile component
sets, GeoJSON, GeoPackage, FlatGeobuf, and GeoParquet uploads. Multi-layer
GeoPackages require a `layer` field.

The browser client is developed separately under `apps/web`; see its README for
local commands. Do not expose the development server publicly.

KML and GML are intentionally rejected by the public upload endpoint because
XML-based formats can introduce external-resource risks. For Internet-facing
deployments, place authentication, rate limiting, request-size enforcement,
structured access logging, and TLS at a trusted reverse proxy or gateway.

## Documentation

- [Documentation index](docs/index.md)
- [Architecture](docs/architecture.md)
- [CLI reference](docs/cli.md)
- [API and deployment](docs/api.md)
- [Developer guide](docs/development.md)
- [FAQ](docs/faq.md)
- [Security policy](SECURITY.md)
- [Release checklist](docs/release-checklist.md)

Only names exported directly from `geoqc` are considered stable public API in
the `0.x` series. Other modules are advanced APIs and may change with notice in
[CHANGELOG.md](CHANGELOG.md).

## Development

```bash
uv sync --all-extras --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
npm --prefix apps/web ci
npm --prefix apps/web run check
```

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

Copyright (c) 2026 Ananda Gunawan.

GeoQC is open-source software distributed under the [MIT License](LICENSE).
