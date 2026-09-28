# Spatial intelligence

GeoQC provides three independent, typed Shapely workflows. Thresholds use the
input CRS units, so projected metric data is strongly recommended for distance
and area decisions.

## Smart Boundary Snap

`snap_boundaries` closes gaps between polygon boundaries when their distance is
within `BoundarySnapConfig.tolerance`. To avoid excessive edits, it uses the
lower-index polygon as a stable anchor and changes only the later polygon. A
candidate is rejected when it is invalid, exceeds `max_shape_shift`, exceeds
`max_relative_area_change`, or creates/increases an overlap.

```python
from pathlib import Path
from shapely.geometry import box
import geoqc
from geoqc import BoundarySnapConfig
from geoqc.infrastructure.reporting.spatial_intelligence_map import SpatialIntelligenceMap

result = geoqc.snap_boundaries(
    [box(0, 0, 1, 1), box(1.005, 0, 2.005, 1)],
    BoundarySnapConfig(tolerance=0.01, max_relative_area_change=0.01),
)
print(result.total_area_before, result.total_area_after, result.total_area_delta)
SpatialIntelligenceMap().boundary_snap(result, Path("snap-preview.html"))
```

The result is a preview: each feature contains before/after WKT, area before and
after, Hausdorff shape shift, anchor indices, status, and rejection reason.

## Road Network Analyzer

`analyze_road_network` reports:

- **Dangling Road**: a short segment with an unconnected endpoint.
- **Dead End**: an endpoint with graph degree one.
- **Broken Connection**: an endpoint almost touching another line.
- **Duplicate Segment**: lines within duplicate tolerance and overlap ratio.
- **Loop Error**: an unexpectedly short closed line.
- **Unnoded Intersection**: crossing or T-junction that is not an endpoint of
  both segments.

All parts of a `MultiLineString` are inspected and findings retain the original
feature index.

```python
report = geoqc.analyze_road_network(
    lines,
    geoqc.RoadNetworkConfig(
        connection_tolerance=0.5,
        dangling_length_threshold=5,
        duplicate_tolerance=0.01,
        duplicate_overlap_ratio=0.98,
        max_loop_length=10,
    ),
)
print(report.issue_counts)
json_report = report.to_dict()
SpatialIntelligenceMap().roads(report, [line.wkt for line in lines], "roads.html")
```

`to_dict()` is suitable for JSON serialization and includes categorized counts
plus feature indices, issue location, message, and measured value per finding.

## Road Network Repair

`repair_road_network` closes endpoint gaps up to an explicit tolerance and then
fully nodes the linework. Every crossing and T-junction becomes a segment
endpoint. The result does not mutate its inputs and every output segment carries
the source feature indices needed to restore dataset attributes.

```python
result = geoqc.repair_road_network(
    lines,
    geoqc.RoadNetworkRepairConfig(
        snap_tolerance=0.1,  # input CRS units
        minimum_segment_length=1e-9,
    ),
)
repaired_lines = [shapely.from_wkt(item.geometry_wkt) for item in result.segments]
print(result.snapped_endpoint_count, result.output_segment_count)
```

Use a projected CRS and choose `snap_tolerance` from the data accuracy. A zero
tolerance disables snapping but still nodes exact intersections. Segment
provenance can contain multiple source indices when the input contains duplicate
or overlapping linework. Repair output is 2D because GEOS topology operations
do not use Z; preserve elevation attributes separately when working with 3D data.

For file-to-file repair, use the CLI. It preserves source attributes, adds
`_geoqc_segment`, `_geoqc_sources`, `_geoqc_length`, and `_geoqc_layer` audit
columns, and writes the result atomically to a new GeoPackage:

```bash
geoqc repair-roads roads.shp repaired.gpkg \
  --snap-tolerance 0.1 \
  --output-layer repaired_roads \
  --report repair-report.json
```

Existing output is rejected unless `--overwrite` is supplied. Multi-layer
GeoPackages require `--layer`. Nonzero snapping on a geographic CRS is rejected
unless `--allow-geographic` is explicitly supplied; reprojecting to a metric CRS
is strongly preferred.

## Small Polygon Intelligence

The analyzer uses configurable area, compactness, isolation, merge-distance,
and target-area-change thresholds. Classification priority is noise, sliver,
then tiny island. Recommendations are:

- **Merge** when a nearby target produces a valid union within the target area
  safety limit. `preview_wkt` contains the proposed union.
- **Delete** for noise/tiny islands without a safe merge target.
- **Ignore** for slivers requiring manual review when no safe merge exists.

```python
report = geoqc.analyze_small_polygons(
    polygons,
    geoqc.SmallPolygonConfig(
        sliver_area_threshold=2,
        sliver_compactness_threshold=0.1,
        tiny_island_area_threshold=1,
        isolation_distance=10,
        noise_area_threshold=0.01,
        merge_tolerance=0.5,
        max_target_area_change=0.02,
    ),
)
SpatialIntelligenceMap().small_polygons(report, "small-polygons-preview.html")
```

No source geometry is mutated; users inspect the report and HTML preview before
applying a recommendation in their own persistence workflow.

## Benchmark

Run the deterministic synthetic benchmark with:

```bash
uv run python benchmarks/spatial_intelligence.py --features 5000
```

It prints elapsed time and features/second for all three engines. Compare runs
using the same Python, GEOS, hardware, feature count, and configuration.
