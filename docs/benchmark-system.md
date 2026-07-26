# Benchmark system

GeoQC can collect resource metrics around every dataset audit and export a
self-contained report. Benchmarking is **opt-in**: the normal audit path uses a
no-op recorder and performs no clock reads, memory probes, metric conversion, or
report allocation.

## Usage

```bash
# HTML (default, includes CSS bar charts)
geoqc audit data/ --benchmark --benchmark-output reports/benchmark.html

# JSON for automation
geoqc audit data/ --benchmark --benchmark-output reports/benchmark.json

# Markdown with a Mermaid runtime chart
geoqc audit data/ --benchmark --benchmark-output reports/benchmark.md

# Explicit configuration included in every record
geoqc audit data/ --benchmark --workers 4 --chunk-size 8192 \
  --benchmark-output reports/benchmark.json
```

The suffix selects `html`, `json`, or `markdown`. Use `--benchmark-format` to
override suffix inference. `--no-benchmark` (the default) completely disables
measurement and does not create a report.

## Recorded fields

Each successful dataset audit produces one record:

| Field | Definition |
|---|---|
| `runtime_seconds` | Monotonic wall-clock duration around engine execution. |
| `cpu_time_seconds` | User + system CPU time consumed by the current worker process. |
| `cpu_usage_percent` | `cpu_time_seconds / runtime_seconds * 100`; it can exceed 100% if native code uses multiple threads. |
| `memory_usage_bytes` | Non-negative RSS change between the end and start snapshots. This is a delta, not total allocation. |
| `peak_memory_bytes` | Highest process working set/high-water mark observed by the OS for that worker process. |
| `feature_count` | Features processed by the audit result. |
| `geometry_count` | Geometries processed. The current geometry audit has one geometry slot per feature, so this equals feature count. |
| `rule_count` | Number of registered rules supplied to the benchmark context. Geometry-only CLI audits currently report `0`. |
| `engine` | Engine selected by automatic engine detection. |
| `chunk_size` | Streaming chunk size configured for the audit. |
| `worker_count` | Effective process-pool size used for the batch. |

The report also contains aggregate totals. Peak memory is the maximum worker
peak—not the sum—while average CPU usage is the arithmetic mean of records.

## Output and visualization

- **JSON** uses schema version `1.0` and contains `summary` plus ordered
  `records`. It is suitable for CI comparisons and ingestion.
- **Markdown** contains a summary, complete metric table, and Mermaid
  `xychart-beta` runtime chart. Renderers without Mermaid still show the table.
- **HTML** is a standalone file with no network dependencies or JavaScript. It
  includes runtime and peak-memory CSS bar charts and a scrollable metric table.

Reports are written through a temporary sibling and atomically replace the
destination after rendering. Parent directories are created automatically.

## Architecture and extensibility

The benchmark implementation follows the repository boundaries:

- `application/benchmarking/models.py`: immutable metric/report values;
- `application/benchmarking/recorder.py`: recorder protocol and zero-cost
  `NoOpBenchmarkRecorder`;
- `infrastructure/benchmarking/recorder.py`: OS process probes and clock-based
  recorder;
- `infrastructure/reporting/benchmark_report.py`: output adapters;
- `infrastructure/gis/parallel_audit.py`: composition at the dataset audit
  boundary.

Callers can inject another `BenchmarkRecorder` without coupling application
models to operating-system APIs. The worker is a pickle-safe callable, so
benchmarking remains compatible with spawn-based multiprocessing on Windows and
macOS.

## Performance design

Enabled measurement performs only two monotonic clock reads, two process CPU
clock reads, and two OS memory snapshots per complete dataset audit. It does not
sample per feature or per chunk, does not start a monitor thread, and renders
reports only after all workers finish. Consequently overhead is approximately
constant per dataset rather than proportional to feature count.

Measure overhead on the target platform with:

```bash
uv run python benchmarks/benchmark_overhead.py \
  --iterations 20 --duration 0.05 --rounds 7
```

The script compares the no-op and process recorder around identical synthetic
operations. Run it on an otherwise idle host and use longer durations to model
real audits; very short operations exaggerate fixed probe cost.

## Platform notes and limitations

- Windows memory values come from `GetProcessMemoryInfo` working-set counters.
- Linux current RSS comes from `/proc/self/statm`; peak RSS comes from
  `getrusage`. Other Unix platforms fall back to the process high-water mark.
- Peak memory is an OS process high-water mark and can include allocations made
  before the measured audit in a reused worker. It is useful for capacity
  planning but is not an isolated Python allocation peak.
- Failed audits do not produce a completed metric record because engine
  execution did not return a valid audit result. Failures remain visible in the
  normal batch result.

## Programmatic API

```python
from geoqc.application.benchmarking import BenchmarkContext
from geoqc.infrastructure.benchmarking import ProcessBenchmarkRecorder

recorder = ProcessBenchmarkRecorder()
value, metrics = recorder.measure(
    operation=lambda: run_audit(),
    context=BenchmarkContext(
        source="roads.gpkg",
        chunk_size=16_384,
        worker_count=4,
        rule_count=8,
    ),
    describe=lambda result: (
        result.feature_count,
        result.geometry_count,
        result.engine,
    ),
)
```