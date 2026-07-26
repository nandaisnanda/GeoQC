# Parallel streaming audits

GeoQC can audit multiple independent datasets concurrently while each dataset
continues to use the bounded-memory streaming engine. Parallelism is deliberately
implemented at the **dataset level**, not inside a dataset's chunk loop.

```text
folder discovery (sorted)
        |
        v
parallel scheduler -- CPU/RAM safety policy --> worker processes
                                                |-- dataset A -> streaming chunks
                                                |-- dataset B -> streaming chunks
                                                `-- dataset C -> streaming chunks
        |
        v
deterministic aggregator (original source order)
```

## CLI

Audit every supported dataset in a directory (one level deep; add
`--recursive`/`-r` to descend into subdirectories):

```bash
geoqc audit path/to/folder
```

Worker count is automatic. A power user can set an upper bound:

```bash
geoqc audit path/to/folder --workers 4
```

`--workers` is not an instruction to exceed safe capacity. GeoQC clamps it to
the number of datasets, logical CPUs, and the current memory budget. Progress is
rendered on a single terminal line. Each dataset failure is reported separately;
other datasets continue and the command returns a non-zero exit code when any
item fails.

Supported discovery suffixes are `.gpkg`, `.shp`, `.geojson`, `.json`, and
`.parquet`. A Shapefile is scheduled once from its `.shp` path; sidecars are not
treated as separate inputs.

## Scheduling and safety

`ParallelScheduler` creates a `ParallelPlan` with:

- `min(dataset count, logical CPU count)` as the CPU ceiling;
- a memory ceiling derived from available memory and a conservative reserve;
- a per-worker allowance so concurrent streaming buffers stay bounded;
- one worker as a guaranteed fallback when memory telemetry is unavailable;
- serial execution when only one worker is safe.

The default process start method is `spawn`. This is the cross-platform-safe
choice for GDAL/GEOS-backed workloads and avoids inheriting initialized native
library state from the parent process. Worker callables and their arguments must
therefore be pickleable.

The scheduler snapshots memory before execution. It does not dynamically add
workers later: stable concurrency is more predictable than reacting to noisy
system-wide memory readings. If process-pool startup fails, GeoQC falls back to
serial execution. A genuine `MemoryError` raised by a dataset is isolated to that
dataset and is not retried concurrently.

## Determinism and compatibility

Workers may finish in any order, but `ParallelBatchExecutor` places every result
back into its original input position. The returned `BatchResult` and CLI output
are therefore deterministic. Within a dataset, the existing streaming reader,
processor, collector, chunk order, and finding limits remain unchanged.

The execution path is read-only. GeoQC never modifies source datasets. A
parallel worker delegates engine selection to `AutomaticGeometryAuditEngine`, so
small datasets retain GeoPandas behavior and large datasets retain streaming
behavior. The public single-dataset APIs are unchanged.

## Python composition API

The application service can be used with any top-level, pickleable worker:

```python
from pathlib import Path

from geoqc.application.parallel import ParallelBatchExecutor
from geoqc.infrastructure.gis.parallel_audit import audit_dataset

sources = [Path("a.gpkg"), Path("b.parquet")]
result = ParallelBatchExecutor().run(sources, audit_dataset, requested_workers=4)
```

Inject `memory_probe`, `cpu_probe`, or `executor_factory` when deterministic
scheduler tests or a different process host are required.

## Benchmarking

The benchmark creates independent GeoPackages and compares `1`, `2`, `4`, and
`8` requested workers:

```bash
uv run python benchmarks/parallel_streaming.py --datasets 8 --features 100000
```

It prints elapsed time, datasets/second, features/second, speedup over one worker,
and the **effective** worker count after safety clamping. Results are workload and
storage dependent: geometry complexity, SSD throughput, GDAL driver behavior,
CPU topology, and available RAM all affect scaling. The benchmark is not a CI
pass/fail gate.

## Limitations

- Parallelism is across datasets only; one very large dataset still uses one
  streaming worker.
- GeoPackage layers are not expanded into separate jobs; a path follows the same
  default-layer behavior as the existing audit engine.
- Process startup has overhead, so serial execution can be faster for tiny jobs.
- Native GIS libraries and storage bandwidth can limit scaling before CPU does.
- CLI progress counts completed datasets, not chunks within each dataset.
