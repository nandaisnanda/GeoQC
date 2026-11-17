# Benchmark findings

Behaviour the synthetic recall benchmark in `tools/benchmark/` uncovered in the audit.
Each entry names the code path and how the benchmark handles it. Nothing here changes `src/`.

## TOP-SLIVER is gated on the profile name generic-polygon

`audit_geodataframe` runs `_sliver_issues` only when `profile.name == "generic-polygon"`
(`src/geoqc/infrastructure/gis/dataset_audit.py`). A custom parcel profile, or a renamed
copy of generic-polygon, gets no sliver check. Its minimum area (1 m²) and compactness
(0.05) thresholds are fixed and no profile field reaches them.

Benchmark handling: the sliver defect type is scored under generic-polygon. The new parcel
rules run under a separate `bench-parcels` profile. Under bench-parcels the 2 m² sliver
strips show up as `TOP-MINIMUM-AREA` (threshold 10 m²) instead.

## TOP-NO-OVERSHOOT-UNDERSHOOT reports four findings per undershoot

The benchmark shortens one segment at a four-way crossing by 0.5 to 1.5 m. The rule then
reports four undershoots: one for the shortened end, and one for each of the three other
segments whose ends still meet at the crossing. Those three ends stay connected to each
other, but `_overshoot_undershoot` (`topology_network_rules.py`) tests each neighbouring
line on its own. An end counts as an undershoot whenever some line lies within the
tolerance without touching it, even if other lines meet that end.

At seed 42 the rule emits 80 findings for 20 undershoots, all at distinct
(feature, endpoint) pairs. `_merge_road_endpoints` does not touch this code, so the merge
does not cause the duplication.

Benchmark handling: the benchmark scores an undershoot on the merged endpoint finding
("Possible undershoot"). All four rule findings per crossing count as allowed collateral of
the undershoot (`scoring.ALLOWED_COLLATERAL`), so they never inflate the false positives.

## Planar CRS-unit tolerance: road checks that run in EPSG:4326 read metres as degrees

The benchmark reprojects its metric test data to EPSG:4326 and passes the same numeric
tolerances. The metric-CRS guard skips the jalan topology rules there, but three road
checks still run and read their thresholds in degrees:

- `_merge_road_endpoints` (`dataset_audit.py`) takes the `no_overshoot_undershoot`
  tolerance (2.0) from the profile even when the guard skipped that rule. In EPSG:4326 the
  radius becomes 2 degrees, about 220 km, so it titles every unconnected end
  "Possible undershoot". Undershoots of 4 m (ratio 2, outside the 2 m tolerance) score
  20 of 20 instead of 0 of 20, and the four clean cul-de-sac ends get the same title.
- `_road_issues` sets `connection_tolerance = profile.tolerance or 0.01`. With the guard
  passing tolerance 0, the analyzer uses 0.01 degrees (about 1.1 km) and reports
  `ROAD-BROKEN_CONNECTION` at every dead end.
- `RoadNetworkConfig.dangling_length_threshold` defaults to 1.0. In degrees that covers
  any road shorter than about 110 km, so the 12 m cul-de-sacs come out as
  `ROAD-DANGLING_ROAD`.

The guard covers the profile's topology rules, not the road preset analyzer or the
endpoint merge.

## The metric-CRS guard reports its skip, but the topology status disagrees with the findings

In EPSG:4326 the guard skips the metric rules of jalan and bench-parcels. The audit shows
the skip in `checks[topology].status = skipped`, and jalan also emits
`META-GEOGRAPHIC_CRS`. No skip went silent. Two side effects:

- Only `no_dangles` detects an unnoded T-junction, so its recall cannot be measured in
  EPSG:4326. The benchmark records the row as skipped.
- `_checks_for_result` files `network` findings under the topology check. When the guard
  marks topology as skipped, the `ROAD-*` findings above still appear in the result's
  issue list while the check that owns them reads "skipped".

## Reprojected T-vertices produce micro overlaps and gaps at tolerance 0

A sliver strip or a widened overlap parcel puts a vertex on the middle of a neighbour's
edge. In metres the vertex lies on the edge. After reprojection to EPSG:4326 each edge
stays straight between its own reprojected vertices, so the vertex lands a hair off the
neighbour's edge. generic-polygon runs its overlap and gap checks at tolerance 0 and
reports these areas of 1e-17 to 1e-22 square degrees: 72 overlaps and 17 gaps in one
20-defect overlap file. Real coverages with T-vertices behave the same way after
reprojection.

# PERFORMANCE

## jalan audit time grows close to the square of the road count

One `audit_dataset` call under the jalan preset (rules pointed at the benchmark layer), on
clean benchmark roads in EPSG:32748, one process, Windows laptop. Two grid layouts:

| road grid | roads | audit time |
| --- | ---: | ---: |
| plain grid (four-way crossings only) | 224 | 3.9 s |
| plain grid | 484 | 15.4 s |
| plain grid | 844 | 36.9 s |
| mixed grid (crossings and three-way junctions) | 103 | 0.5 s |
| mixed grid | 270 | 2.0 s |
| mixed grid | 517 | 7.2 s |
| mixed grid | 1040 | 34.7 s |

A least-squares fit of log(time) on log(roads) gives an exponent of 1.83 for the mixed
grid and 1.69 for the plain grid. Extrapolated, a 1,740-road file (the grid that fits 100
isolated unnoded T-junctions) takes about 90 seconds per audit.

## Profiled cause: two network rules scan every pair of lines

Earlier hypothesis: `_overshoot_undershoot` dominates. cProfile of one audit at 270 roads
(4.75 s total, top entries by cumulative time) shows a different main cost:

| function (`src/geoqc/infrastructure/gis/`) | cumulative time | share |
| --- | ---: | ---: |
| `topology_service.py: evaluate_topology_rules` | 4.08 s | 86% |
| `topology_network_rules.py: _endpoint_issues` (no_dangles) | 2.90 s | 61% |
| `shapely Point.__new__`, called from `_endpoint_issues` | 1.60 s | 34% |
| `topology_network_rules.py: _overshoot_undershoot` | 1.18 s | 25% |
| `audit_service.py: audit_geometries` (geometry checks and road analyzer) | 0.62 s | 13% |
| `road_network_analysis.py: analyze` | 0.37 s | 8% |

`_endpoint_issues` checks each endpoint against both endpoints of every other line in a
Python loop, and builds a new shapely `Point` for each of those endpoints on every pass:
92,638 `Point` objects for 270 roads. `_overshoot_undershoot` loops over every pair of
lines and computes an intersection for each pair (146,520 calls). Neither uses a spatial
index. `road_network_analysis.py` does the same job with an `STRtree` and costs a tenth as
much.

The benchmark keeps its road grid as small as the defect count allows.
