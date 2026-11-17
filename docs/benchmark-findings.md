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

## jalan audit time grows with the square of the road count

| roads | audit time |
| ---: | ---: |
| 224 | 3.9 s |
| 484 | 15.4 s |
| 844 | 36.9 s |

`_overshoot_undershoot` (`topology_network_rules.py`) compares every line with every other
line and computes an intersection for each pair. The benchmark keeps its road grid as small
as the defect count allows.
