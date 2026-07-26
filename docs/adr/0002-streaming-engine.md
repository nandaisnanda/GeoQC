# ADR 0002: Arrow-based streaming audit pipeline

- Status: Accepted
- Date: 2026-07-24

## Context

GeoPandas materializes complete datasets. This makes audit memory proportional
to dataset size and prevents reliable processing of millions of features.
Audit output and public interfaces must remain stable.

## Decision

Introduce application-layer streaming ports and an orchestrator separated into
reader, iterator, processor, and collector roles. Use Arrow record batches as
the infrastructure/application boundary, Pyogrio's GDAL Arrow stream for OGR
formats, and PyArrow's scanner for GeoParquet. Feed each batch to the existing
Rule Engine through an adapter and merge results in source order.

Collectors own retention policy: aggregate values remain exact while detailed
geometry findings may be bounded. Readers are selected by an explicit registry
so adding a format does not modify the engine.

## Consequences

- Peak working memory is bounded by batch size plus retained result state.
- Existing Rule Engine and API contracts remain available.
- Readers must preserve order and contiguous offsets.
- Dataset-wide rules need purpose-built mergeable partial state; they must not
  retain every feature.
- Arrow/GDAL exceptions are normalized at the infrastructure boundary.