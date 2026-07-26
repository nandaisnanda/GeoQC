# API and deployment

GeoQC ships an optional FastAPI service that exposes geometry validation and
safe topology-repair previews over HTTP for the bundled `apps/web` client or
other local tooling. It is not installed by default.

```bash
python -m pip install "geoqc[api]"
python -m uvicorn geoqc.interfaces.api.main:app --host 127.0.0.1 --port 8000
```

The service binds to `127.0.0.1` by default in the example above. It has no
authentication, rate limiting, or TLS built in — see
[Deployment guidance](#deployment-guidance) before exposing it beyond your
own machine.

## Configuration

The service reads two optional environment variables (see
[.env.example](../.env.example)):

| Variable            | Default       | Effect                                                                 |
| ------------------- | ------------- | ----------------------------------------------------------------------- |
| `GEOQC_ENVIRONMENT` | `development` | Set to `production` to disable `/docs`, `/redoc`, and `/openapi.json`. |
| `GEOQC_LOG_LEVEL`   | `INFO`        | Standard library logging level applied at startup.                     |

## Endpoints

### `POST /api/geometry/validate`

Also available, undocumented, at `POST /api/geometry/validate-shapefile`
(kept for backward compatibility with the web client; both paths share the
same handler).

Validates every geometry in one bounded, allowlisted geospatial dataset and
returns per-feature issues.

**Request body** (`application/json`):

```jsonc
{
  "files": [
    { "name": "parcels.geojson", "content_base64": "..." }
  ],
  "layer": null // optional, GeoPackage only
}
```

- `files`: 1 to 5 components. A single GeoJSON (`.geojson`/`.json`),
  GeoPackage (`.gpkg`), or FlatGeobuf (`.fgb`) file, **or** the full set of
  Shapefile components (`.shp`, `.shx`, `.dbf`, plus optional `.prj`/`.cpg`)
  sharing the same base name.
- Each file's `content_base64` is base64-encoded file content. The total
  decoded upload is capped at 100 MiB.
- `layer`: required only when addressing a specific layer in a multi-layer
  GeoPackage; rejected for every other format.

**Response body** (`200 OK`):

```jsonc
{
  "filename": "parcels.geojson",
  "layer": null,
  "feature_count": 1200,
  "valid_feature_count": 1180,
  "invalid_feature_count": 20,
  "issue_counts": { "self_intersection": 12, "empty_geometry": 8 },
  "findings": [
    { "feature_index": 4, "issues": [{ "type": "self_intersection", "message": "..." }] }
  ],
  "findings_truncated": false
}
```

`findings` is capped at 1,000 entries; `findings_truncated` is `true` when
more invalid features exist than are listed.

**Error responses:**

| Status | Meaning                                                                 |
| ------ | ------------------------------------------------------------------------ |
| `400`  | Unsafe or duplicate filename, invalid base64, wrong/mismatched extensions, missing Shapefile component, or an invalid `layer` parameter. |
| `413`  | Upload exceeds 100 MiB, or the dataset exceeds 1,000,000 features.       |
| `422`  | File content does not match its extension, the dataset could not be parsed, or it has no geometry column. |

Error bodies use FastAPI's standard `{"detail": "..."}` shape. Internal
exceptions are logged server-side and never returned to the client (see
`tests/unit/interfaces/test_api.py`).

**Rejected formats:** KML and GML are intentionally not accepted, because
XML-based formats can introduce external-entity/resource risks. Use a
converted GeoJSON, GeoPackage, or Shapefile instead.

### `POST /api/geometry/repair`

Computes a **non-mutating preview** of intelligent topology repair for a
bounded dataset. It supports self-intersections, invalid rings, duplicate
vertices, sliver polygons, cross-feature overlaps, and small enclosed gaps.
The response retains source attributes, converts output GeoJSON to WGS84 when
the input CRS is known, and contains both original and repaired snapshots.

The `files` and `layer` fields follow the validation endpoint. Repair is more
strictly bounded to 50,000 features because overlap and gap processing needs a
whole coverage in memory.

```jsonc
{
  "files": [
    { "name": "parcels.geojson", "content_base64": "..." }
  ],
  "layer": null,
  "mode": "preview",
  "options": {
    "duplicate_vertex_tolerance": 0.0,
    "sliver_area_threshold": 1e-9,
    "sliver_thinness_threshold": 1e-3,
    "gap_area_threshold": 1e-6,
    "max_shape_shift": null,
    "max_relative_area_change": null
  }
}
```

All thresholds use the input geometry's coordinate units; area thresholds use
squared units. `max_shape_shift` and `max_relative_area_change` are optional
safety budgets. A candidate that exceeds either budget is rejected and the
original feature is retained.

The response is a repair report containing aggregate counts, an action
breakdown, area/shape metrics, up to 1,000 changed-feature findings with
full-precision `before_wkt` and `after_wkt`, and two serialized FeatureCollections:

- `original_geojson` — immutable pre-repair snapshot.
- `repaired_geojson` — candidate output preserving feature properties.

`findings_truncated` indicates that additional changed features exist. The
endpoint intentionally accepts only `mode: "preview"`: it never overwrites the
uploaded source. The web client implements **Apply** by selecting the returned
candidate for download and **Undo** by returning to the retained original
snapshot. Persistent, multi-level snapshot undo for Python workflows is
provided by `open_repair_session`; see
[Intelligent topology repair](topology-repair.md#preview-apply-and-undo).

Repair uses the same `400`, `413`, and `422` error families as validation. A
`413` is also returned when the repair-specific 50,000-feature limit is
exceeded.

### `GET /docs`, `GET /redoc`, `GET /openapi.json`

Interactive OpenAPI documentation, enabled by default and disabled when
`GEOQC_ENVIRONMENT=production` (see [Configuration](#configuration)).

## Deployment guidance

The API is designed to sit behind infrastructure you control. For any
deployment reachable outside your own machine, add at your reverse proxy or
gateway:

- Authentication and authorization.
- Rate limiting and request-size enforcement (in addition to the 100 MiB
  application-level cap).
- TLS termination.
- Structured access logging.
- `GEOQC_ENVIRONMENT=production` to disable the interactive API docs.

The bundled `apps/web` client talks to the API via a relative `/api/...`
path with no configurable base URL, so it must be served from the same
origin as the API (directly, or via a reverse proxy that unifies both). Do
not expose the Vite development server (`npm run dev`) publicly; build a
static bundle with `npm run build` for anything beyond local development.
