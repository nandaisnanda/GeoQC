# ADR 0004: Dataset-level process parallelism for streaming audits

- Status: Accepted
- Date: 2026-07-24

## Context

The streaming engine bounds memory for one large dataset, but folder audits over
many independent datasets leave CPU capacity unused. Geometry validation is
CPU-heavy and GDAL/GEOS-backed execution must remain isolated and cross-platform.
The existing per-dataset output and deterministic ordering cannot change.

## Decision

GeoQC parallelizes **between datasets** with a spawn-based process pool. Each
worker invokes the existing automatic geometry audit engine; streaming remains
sequential inside each dataset.

The application layer owns a scheduler, safety policy, executor, progress event
model, and deterministic result aggregation. Infrastructure owns the concrete
GIS audit worker. CLI owns folder discovery and terminal rendering.

Worker count is the minimum of dataset count, logical CPU count, the requested
upper bound, and a conservative available-memory allowance. Unsafe or impossible
parallel plans fall back to one worker. Results are stored by input index rather
than completion order, and individual failures are represented as batch items.

## Consequences

### Positive

- Multi-dataset audits can use multiple CPU cores.
- Per-dataset streaming memory bounds and engine output remain intact.
- A corrupt dataset does not stop unrelated work.
- Scheduling is testable without GIS dependencies.
- Spawn semantics avoid inherited native-library state.

### Negative

- Serialization and process startup add overhead.
- One huge dataset does not gain intra-dataset CPU parallelism.
- Storage bandwidth may become the bottleneck.
- Memory telemetry is a conservative snapshot rather than dynamic admission
  control.

## Rejected alternatives

- **Threads:** geometry work is CPU-heavy and native-library thread behavior is
  less isolated.
- **Parallel chunks within one dataset:** complicates deterministic findings,
  reader safety, and bounded-memory guarantees.
- **Unbounded CPU-count pool:** can multiply chunk buffers and exhaust RAM.
- **Completion-order output:** faster to emit but breaks deterministic reports.
