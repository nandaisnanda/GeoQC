# GeoQC

[![CI](https://github.com/GeoQC/geoqc/actions/workflows/ci.yml/badge.svg)](https://github.com/GeoQC/geoqc/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/geoqc.svg)](https://pypi.org/project/geoqc/)
[![Python versions](https://img.shields.io/pypi/pyversions/geoqc.svg)](https://pypi.org/project/geoqc/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**GeoQC** is a typed Python toolkit for quality control of geospatial data. It
detects common geometry defects and provides reusable building blocks for CRS,
datum, axis-order, attribute, batch, and reporting workflows.

> **Release status:** `0.1.0` (alpha). The top-level `validate_geometry()` API is
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
- Stream GeoPackage, Shapefile, GeoJSON, and GeoParquet audits in bounded
  Arrow chunks without loading the complete dataset into RAM.
- Audit independent datasets concurrently with memory-aware process scheduling,
  isolated failures, and deterministic output ordering.
- Inspect CRS consistency, axis order, and possible datum shifts.
- Run typed, extensible quality rules with immutable result models.
- Process bounded batches and generate optional HTML or interactive reports.
- Expose a hardened FastAPI upload endpoint and a responsive React client.

GeoQC does not repair or silently modify source datasets.

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

## Command-line interface

The initial CLI exposes package information and a stable command surface:

```bash
geoqc --help
geoqc --version
geoqc audit path/to/folder
```

Worker count is selected automatically; use `--workers N` as a safe upper bound.
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
