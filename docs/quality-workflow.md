# Dataset quality workflow

The public workflow API is designed for Python applications, notebooks, CI,
and future desktop adapters such as a QGIS plugin. It never edits a source
layer. Findings carry WKT geometry and stable fields so a UI can create
clickable point, line, and polygon issue layers.

## One-call file workflow

`audit_dataset()` is the stable, dataset-level entry point for a read-only
audit. It uses the existing automatic geometry engine, CRS guard, and attribute
scanner and returns a deterministic `DatasetAuditReport`:

```python
import geoqc

report = geoqc.audit_dataset("data.gpkg", layer=None, schema=None, checks="all")
for check in report.checks:
    print(check.name, check.status, check.reason, check.issue_count)
```

Every report contains file/layer metadata, selected engine, feature count,
per-check status, issue counts, feature indices, severity, and recommendations.
Checks that need a schema, topology rules, reference layers, projected units,
or other missing prerequisites are `skipped`, never silently executed.

`audit_file()` and `audit_geodataframe()` combine geometry, topology, CRS,
and configured attribute checks into one versioned result.

```python
from geoqc import audit_file, load_quality_profile, write_audit_report, write_issue_layers

profile = load_quality_profile("parcel-profile.yaml")
result = audit_file("parcels.gpkg", layer="parcels", profile=profile)

write_issue_layers(result, "parcel-issues.gpkg")
write_audit_report(result, "parcel-report.html")
raise SystemExit(0 if result.passes(profile.gate) else 1)
```

Use `run_quality_workflow()` to perform those steps in one call. Outputs never
replace the input dataset. Existing outputs require an explicit `overwrite`.

## Audit in-memory geometries with a preset

```python
from shapely import box

from geoqc import audit_geometries, issues_to_geodataframe

result = audit_geometries(
    [box(0, 0, 2, 2), box(1, 0, 3, 2)],
    dataset_name="parcels",
    preset="parcel",
    crs="EPSG:32748",
)

print(result.quality_score)
print(result.crs_guard.message)
polygon_issues = issues_to_geodataframe(result, "polygon")
polygon_issues.to_file("parcel-issues.gpkg", layer="geoqc_errors_polygon")
```

Built-in presets are `parcel`, `admin_boundary`, `road`, and `point_survey`.
Every finding includes severity, source feature indexes, a suggested fix,
repair risk (`safe`, `review`, `dangerous`, or `not_repairable`), and its issue
geometry. The CRS guard warns when tolerances use degrees or the CRS is missing.

## Shareable JSON/YAML profiles

Profiles configure presets, stable feature IDs, CRS requirements, topology and
attribute rules, weighted scoring, and CI gates. Start from the complete
[parcel profile example](examples/parcel-profile.yaml). Unknown profile fields,
invalid enum values, missing configured ID columns, and invalid thresholds are
rejected rather than ignored.

Attribute rules currently support `required`, `not_null`, `unique`,
`allowed_values`, and `numeric_range`. `id_column` makes issue fingerprints
stable when rows are reordered. Each serialized finding contains both its
fingerprint and source feature ID.

## Issue layers and versioned results

`write_issue_layers()` writes an atomic GeoPackage containing available
`geoqc_errors_point`, `geoqc_errors_line`, and `geoqc_errors_polygon` layers.
Every layer exposes the code, fingerprint, severity, category, repair risk,
source and related feature IDs, message, and suggested fix.

`DatasetAuditResult.to_dict()` has `schema_version: "1.0"`. Consumers should
select behavior using this field instead of guessing from package versions.
JSON reports use exactly this schema.

## Explainable weighted scoring

Penalties are divided by feature count so a large dataset is not driven to
zero by a small number of issues. Category scores are combined using profile
weights. `result.score_deductions` explains the fingerprint, severity, points,
and formula contribution for every deduction. Mandatory failure thresholds
remain separate through `QualityGatePolicy`.

## Safe repair and preview

`repair_geometries_safely()` only removes duplicate vertices with zero allowed
shape or area change. Use `repair_geometries()` or `open_repair_session()` for
reviewed repairs. Their results retain before/after WKT, action details, area
change, vertex change, and maximum shape shift.

```python
from geoqc import repair_geometries_safely

preview = repair_geometries_safely(geometries)
for feature in preview.report.results:
    print(feature.feature_index, feature.result.status, feature.result.metrics)
```

`build_repair_plan(result)` maps repairable findings to explicit strategies.
Only `safe` actions are marked automatic. Multiple reviewed strategies that
target the same feature are returned as plan conflicts and require a decision
before an adapter applies them.

## Custom cross-layer rules

```python
from geoqc import DatasetLayer, TopologyRule, TopologyRuleType, evaluate_topology_rules

issues = evaluate_topology_rules(
    layers=(
        DatasetLayer("buildings", tuple(item.wkt for item in buildings)),
        DatasetLayer("parcels", tuple(item.wkt for item in parcels)),
    ),
    rules=(
        TopologyRule(
            TopologyRuleType.MUST_BE_INSIDE,
            layer="buildings",
            reference_layer="parcels",
        ),
    ),
)
```

Supported declarative constraints include the original `no_overlap`, `no_gap`,
`no_duplicate`, `must_be_inside`, `must_not_intersect`, and `minimum_area`
rules plus the Phase-2 topology rules below.

| Rule | Required configuration | Meaning |
| --- | --- | --- |
| `boundary_must_match` | `reference_layer` | Every source boundary section must lie on a reference boundary. `tolerance` permits a small offset. |
| `no_dangles` | optional `tolerance` | Line endpoints must coincide with another line endpoint. |
| `endpoint_must_connect` | optional `tolerance` | Line endpoints must connect anywhere on another line, including a T-junction. |
| `no_overshoot_undershoot` | positive `tolerance` | Finds short tails beyond intersections and endpoints stopping just short of another line. |
| `allowed_geometry_type` | `allowed_geometry_types` | Restricts Shapely geometry type names, such as `Point` or `Polygon`. |
| `singlepart_only` | none | Rejects multi-geometries and geometry collections. |
| `no_spikes` | positive `minimum_angle` | Finds vertices with an interior angle below the threshold in degrees. |
| `minimum_segment_length` | positive `minimum_length` | Finds consecutive vertices forming a short segment. |
| `minimum_vertex_distance` | positive `minimum_distance` | Finds non-adjacent vertices that are too close. |
| `must_touch`, `must_intersect`, `must_cover` | `reference_layer` | Applies the named spatial predicate against a reference feature. |
| `attribute_overlap` | `attribute_column`, `overlap_policy` | Controls polygon overlap with `deny_all`, `allow_equal`, or `allow_different`. |
| `precision_grid` | positive `precision_grid_size` | Finds vertices off-grid by more than `tolerance`; it does not mutate coordinates. |

For example, this profile fragment permits overlap only between parcels with
the same zoning class and checks a centimetre coordinate grid:

```yaml
topology_rules:
  - type: attribute_overlap
    layer: parcels
    attribute_column: zone
    overlap_policy: allow_equal
  - type: precision_grid
    layer: parcels
    precision_grid_size: 0.01
    tolerance: 0.000001
```

Distance, length, and precision values use the layer CRS coordinate units;
`minimum_angle` is always expressed in degrees. Attribute overlap rules loaded
through `audit_geodataframe()` or `audit_layers()` read the named column from
the source frame. All Phase-2 checks are detection-only and include issue WKT,
feature indices, metrics, and a suggested review action.

## Reports and CI gates

Use `write_audit_report(result, "report.json")` for the versioned machine
contract or `write_audit_report(result, "report.html")` for a self-contained
human report. A quality gate provides deterministic CI behavior without
parsing console text:

```python
from geoqc import QualityGatePolicy

policy = QualityGatePolicy(minimum_score=90, fail_on="error")
raise SystemExit(0 if result.passes(policy) else 1)
```

For baseline/version comparison, use `DatasetSnapshot` and
`compare_datasets()`. The result records added, removed, modified, and unchanged
features, attribute and schema changes, CRS equality, and boundary differences.
