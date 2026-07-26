# Intelligent topology repair

GeoQC detects geometry defects and can also repair them with the smallest change
that makes the geometry valid. Repair is opt-in, reversible, and reported: every
result stores the geometry **before and after**, the exact actions taken, and how
much the shape moved.

The same engine backs the Python API, so repairs are reproducible and identical
to what a script or a future CLI/HTTP surface would produce. No repair logic runs
in the browser.

## What it repairs

| Issue                | Scope           | Strategy                                                        |
| -------------------- | --------------- | -------------------------------------------------------------- |
| Self-intersection    | Single geometry | GEOS `make_valid` (splits a bow-tie into valid parts)          |
| Invalid ring         | Single geometry | GEOS `make_valid`                                              |
| Duplicate vertex     | Single geometry | `remove_repeated_points` (drops coincident consecutive points) |
| Sliver polygon       | Single geometry | Drop parts below an area/thinness threshold                    |
| Overlap              | Coverage        | *Erase* — earlier features keep disputed area                  |
| Gap (enclosed)       | Coverage        | Fill holes below an area threshold into the widest neighbour   |

Single-geometry defects are fixed independently per feature. **Overlap** and
**gap** are cross-feature problems: they are only meaningful for a set of
geometries treated as one coverage, so they are handled by the coverage API.

## Design guarantees

- **Minimal change.** `make_valid` preserves as much of the original as possible;
  duplicate-vertex and sliver passes only remove degenerate data.
- **Before/after is always kept.** Results carry `before_wkt` and `after_wkt` at
  full coordinate precision, so any repair can be inspected or reverted.
- **Preview or apply.** Compute a report without mutating anything, or commit the
  change to a working set.
- **Undo.** Every `apply` snapshots the prior state; applies can be undone in
  reverse order.
- **Honest about limits.** Overlap resolution uses a deterministic *erase* policy
  (feature order defines priority). Gap filling only closes **enclosed** holes
  below `gap_area_threshold`; open gaps at the coverage edge are left untouched.

## Configuration

`RepairConfig` exposes conservative defaults so ordinary geometries are never
altered. Thresholds are in the geometry's own coordinate units (squared for
areas), so scale them for degrees vs. metres.

```python
from geoqc import RepairConfig

config = RepairConfig(
    remove_duplicate_vertices=True,
    duplicate_vertex_tolerance=0.0,
    fix_invalid=True,
    remove_slivers=True,
    sliver_area_threshold=1e-9,
    sliver_thinness_threshold=1e-3,
    resolve_overlaps=True,
    fill_gaps=True,
    gap_area_threshold=1e-6,
)
```

## Repair one geometry

```python
from shapely.geometry import Polygon

from geoqc import repair_geometry

bowtie = Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])
result = repair_geometry(bowtie)

print(result.status)  # RepairStatus.REPAIRED
print(result.is_changed)  # True
print([a.issue_type for a in result.actions])
print(result.before_wkt)  # original geometry
print(result.after_wkt)  # repaired, valid geometry
print(result.metrics.area_delta, result.metrics.shape_shift)
```

`shape_shift` is the Hausdorff distance between the original and repaired
geometry — a single number for "how far did the shape move".

## Repair a coverage (overlap and gaps)

```python
from shapely import box

from geoqc import repair_geometries

# Two overlapping polygons; the first keeps the shared area.
coverage = repair_geometries([box(0, 0, 2, 2), box(1, 0, 3, 2)])

print(coverage.report.action_counts)  # {"overlap": 1}
for after in coverage.after_wkt:
    print(after)
```

`coverage.report` is a `RepairReport`: it aggregates repaired/unchanged/failed
counts, per-issue action counts, total area delta, and the maximum shape shift,
and serializes with `report.to_dict()` for JSON output.

## Preview, apply, and undo

```python
from shapely.geometry import Polygon

from geoqc import open_repair_session

session = open_repair_session([Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])])

report = session.preview()  # nothing is mutated
print(report.repaired_count)  # 1

session.apply()  # commit; snapshot the previous state
print(session.can_undo)  # True

session.undo()  # restore the pre-apply geometries
print(session.can_undo)  # False
```

`session.geometries` returns the current working set as WKT. Because the working
set and the undo history are WKT snapshots, a session is cheap to keep and fully
reversible.

## HTTP and web workflow

The optional FastAPI service exposes `POST /api/geometry/repair`. The endpoint
accepts the same allowlisted dataset bundle as geometry validation plus repair
thresholds, and always runs in `preview` mode. Its report includes per-feature
before/after WKT and downloadable original/repaired GeoJSON snapshots while
preserving source properties. Repair requests are capped at 50,000 features.

In the bundled web client:

1. **Preview repair** sends the uploaded dataset to the preview endpoint.
2. **Apply preview** selects the repaired snapshot and enables its download; it
   does not overwrite the user's source file.
3. **Undo** deselects that candidate and restores the retained original state.
4. **Download report** exports the audit report without embedding the two large
   GeoJSON snapshots.

This browser state is deliberately local and non-destructive. For repeated
programmatic applies with a multi-level LIFO undo history, use
`open_repair_session` as shown above. The complete transport contract and
deployment limits are documented in [API and deployment](api.md).

## Statuses

- `REPAIRED` — at least one action changed the geometry into a valid result.
- `UNCHANGED` — nothing needed repair; the geometry is returned as-is.
- `FAILED` — the geometry could not be made valid safely (it is left untouched).

## Limitations

- Overlap priority is positional. Provide geometries in the order that should win
  disputed area; there is no attribute-based ownership policy yet.
- Only enclosed gaps are filled. Closing gaps along the outer boundary of a
  coverage requires an explicit target extent and is tracked in the
  [roadmap](roadmap.md).
- Thresholds are unit-dependent. In geographic (degree) coordinates the default
  area thresholds are extremely small; set them for your CRS.
- HTTP repair emits GeoJSON as the portable download format. It preserves
  feature properties and represents a known source CRS in WGS84 GeoJSON, but it
  does not rewrite the uploaded GeoPackage/Shapefile in place.
