# Auto Engine Detection

GeoQC chooses the safest execution engine automatically before a geometry audit. The public HTTP contract, rule semantics, finding order, and report data do not change.

## Selection flow

1. Resolve the format-specific streaming reader.
2. Read lightweight dataset metadata.
3. Sample at most 256 features to estimate WKB size and geometry vertex complexity.
4. Estimate the in-memory GeoPandas footprint and inspect currently available physical memory.
5. Apply a deterministic, conservative policy.
6. Log the chosen engine and all decision inputs at `INFO` level.
7. Execute either the in-memory GeoPandas adapter or the existing bounded Streaming Engine.

Profiling is itself bounded: it never loads the full dataset. The sample is processed independently from the actual audit, so audit offsets and results remain unchanged.

## Default policy

Streaming is selected when **any** safety threshold is reached:

- file size is at least 512 MiB;
- feature count is at least 100,000;
- estimated in-memory footprint is at least 2 GiB;
- estimated footprint exceeds 50% of currently available RAM;
- sampled geometry complexity projects to at least 20 million vertices.

Otherwise GeoPandas is used. If metadata is unavailable, the policy falls back to the measurable file size, memory estimate, and bounded sample. Unknown information never causes a full pre-read.

Thresholds are centralized in `EngineSelectionConfig`. The application policy is independent of GeoPandas, Pyogrio, Arrow, and FastAPI; infrastructure adapters provide profiling and execution.

## Observability

Every decision emits one structured-style log record containing:

- selected engine;
- human-readable reason(s);
- feature count;
- file size;
- estimated memory;
- available memory;
- sampled average vertex count.

Set `GEOQC_LOG_LEVEL=INFO` (the default) to observe decisions. Dataset contents and attribute values are never logged.

## Extending the detector

To add a criterion:

1. add a framework-free profile field if required;
2. collect it with a bounded operation in `DatasetProfiler`;
3. add the threshold to `EngineSelectionConfig`;
4. add one deterministic rule in `EngineDecisionService`;
5. cover small, threshold, and resource-pressure cases with unit tests;
6. retain the engine parity integration test.

See [ADR 0003](adr/0003-auto-engine-detection.md) for the architectural decision.
