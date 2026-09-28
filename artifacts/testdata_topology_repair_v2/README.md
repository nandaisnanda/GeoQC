# GeoQC testdata topology repair

The source Shapefiles were not overwritten. The repaired network is stored in
`geoqc_testdata_repaired.gpkg` in its original projected CRS.

## Configuration

- CRS: `EPSG:32749`
- Endpoint snap tolerance: 0.1 metre
- Minimum retained segment length: 1e-08 metre

## Result

| Check | Before | After |
| --- | ---: | ---: |
| Input/output features | 233 | 537 |
| Line parts | 245 | 537 |
| Invalid features | 0 | 0 |
| Non-simple features | 1 | 0 |
| Unnoded intersection pairs | 302 | 0 |
| Linear-overlap pairs | 0 | 0 |
| Near-gap endpoints | 23 | 0 |
| Dead-end endpoints (manual review) | 336 | 50 |
| Sub-metre line parts (retained) | 3 | 5 |
| Exact duplicate segments | 0 | 0 |

The repair snapped 19 endpoints and produced
537 fully noded segments from
245 source line parts. `network_all` contains the full
network; the three named layers contain the same repaired segments grouped by
their source road class. Attributes come from the primary source feature and
`source_ids` retains complete provenance.

Dead ends are not automatically deleted: many are legitimate road termini and
need semantic/manual review. Very short valid segments are also retained unless
they are below the explicit minimum length.
