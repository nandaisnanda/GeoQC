# Enterprise spatial intelligence

GeoQC provides deterministic, typed workflows for large spatial quality-control jobs. No
workflow in this module calls an AI model or LLM.

## Spatial duplicate detection

`detect_spatial_duplicates` uses Shapely's `STRtree` spatial index to avoid an all-pairs scan.
Candidate pairs are scored with intersection-over-union, normalized Hausdorff similarity, and
shape similarity. The weighted score is reported as a percentage. `maximum_pairs` places an
explicit ceiling on expensive pair evaluation and the report records truncation and candidate
reduction metrics.

```python
from geoqc import SpatialDuplicateConfig, detect_spatial_duplicates

report = detect_spatial_duplicates(
    geometries,
    SpatialDuplicateConfig(similarity_threshold=0.90, search_tolerance=0.25),
)
```

## Multi-dataset comparison

Create two `DatasetSnapshot` objects and call `compare_datasets`. The resulting difference
report includes feature geometry and attribute changes, CRS equality, schema changes, aggregate
boundary IoU and symmetric-difference area, warnings, and spatial-index candidate counts.

## Spatial conflict analyzer

`analyze_spatial_conflicts` compares semantic `SpatialLayer` roles. Built-in deterministic rules
cover road/river crossings, buildings in rivers, inter-agency polygon overlaps, and boundary
conflicts. Each result includes magnitude, a 0–100 severity score, an explanation, and WKT for
visualization.

## Repair recommendation rule engine

`prioritize_repairs` normalizes area and feature count within a batch, combines them with severity
and impact using explicit `PriorityWeights`, and returns stable ranked recommendations. Scores and
rationales are reproducible and explainable.

## Visualization and web API

`EnterpriseSpatialMap` writes self-contained Folium maps for duplicate, difference, and conflict
reports. Install `geoqc[report]` to use it. The optional FastAPI application exposes:

- `POST /api/spatial/duplicates`
- `POST /api/spatial/compare`
- `POST /api/spatial/conflicts`
- `POST /api/repairs/prioritize`

The React Repair Studio provides before/after geometry comparison, approve/reject, undo, and a
local decision history. Dataset upload limits and pair limits provide bounded website execution.

## Benchmark and scalability

Run the indexed duplicate benchmark with:

```bash
uv run python benchmarks/enterprise_spatial.py --features 10000
```

The output records feature count, duplicate count, evaluated candidates versus theoretical pairs,
candidate reduction, and elapsed time. For production, use a projected CRS when distance or area
thresholds need metric meaning; partition very large datasets and preserve the configured pair cap.