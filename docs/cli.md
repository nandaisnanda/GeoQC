# CLI reference

The `geoqc` console script is installed automatically with the package:

```bash
python -m pip install geoqc
geoqc --help
```

## Current command surface

| Command                       | Description                                      | Exit code |
| ----------------------------- | ------------------------------------------------ | --------- |
| `geoqc --help`                | Show usage and available options.                | `0`       |
| `geoqc --version`             | Print the installed GeoQC version and exit.      | `0`       |
| `geoqc audit PATH`            | Audit supported datasets under a file or folder. | `0`/`1`   |
| `geoqc audit PATH --workers N`| Set a safe requested worker upper bound.          | `0`/`1`   |
| `geoqc crs-scan PATH...`      | Compare declared CRS metadata.                    | `0`/`1`/`2`/`3` |
| `geoqc datum-shift SRC DST`   | Audit a datum transformation over bounds.         | `0`/`1`/`2`/`3` |
| `geoqc axis-order --bounds …` | Classify geographic axis order.                    | `0`/`1`/`2`/`3` |
| `geoqc batch PATH...`         | Audit datasets with isolated per-item outcomes.   | `0`/`1`/`2`/`3` |
| `geoqc html-report IN OUT`    | Write an atomic, self-contained HTML audit.        | `0`/`1`/`2`/`3` |
| `geoqc check DATASET`         | Run unified profile-driven dataset QC.            | `0`/`1`/`2` |
| `geoqc repair-roads IN OUT`   | Snap and fully node a road layer into a new GPKG. | `0`/`2`   |
| `geoqc` (no args)             | Equivalent to `--help`.                          | `0`       |
| Unknown option                | Reject the invocation with a usage error.         | `2`       |

Example:

```console
$ geoqc --version
GeoQC 0.1.0
```

Delivery commands use one stable contract: `0` means the operation completed
and its quality gate passed, `1` means it completed but quality failed, `2`
means invalid input, and `3` means an unexpected internal failure. Batch uses
the highest per-item code and continues after invalid or failed files. The CLI
disables pretty tracebacks and sanitizes unexpected failures.

All five delivery commands support concise human output and deterministic JSON
with `--json`:

```bash
geoqc crs-scan parcels.gpkg roads.geojson --json
geoqc datum-shift EPSG:4267 EPSG:4326 --bounds -125 25 -66 49 --grid-size 5
geoqc axis-order --bounds 106.7 -6.3 106.9 -6.1 --json
geoqc batch data/ --recursive --json
geoqc html-report parcels.gpkg reports/parcels.html --overwrite
```

The default dataset policy validates geometry structure, requires CRS metadata,
and rejects exact duplicate feature geometry. `audit`, `batch`, and
`html-report` all decide quality with the canonical
`DatasetAuditResult.passes()` API. HTML destinations must end in `.html`;
parents are created, existing files require `--overwrite`, and replacement is
atomic.

`geoqc audit` prints the unified dataset report status and issue count while
retaining deterministic file/folder discovery, `--recursive`, multiprocessing,
automatic streaming/in-memory engine selection, benchmarking, and the existing
exit-code contract. Unconfigured schema/topology/spatial checks appear as
explicit skips in the underlying report.

### Profile-driven quality check

Run a complete dataset check with a built-in preset:

```bash
geoqc check parcels.gpkg \
  --layer parcels \
  --preset parcel \
  --issues parcel-issues.gpkg \
  --report parcel-report.html
```

Use a shareable profile for CRS, attributes, scoring, and gate policy:

```bash
geoqc check parcels.gpkg \
  --layer parcels \
  --profile parcel-profile.yaml \
  --issues parcel-issues.gpkg \
  --report parcel-report.json \
  --overwrite
```

`check` returns `0` when the gate passes, `1` when quality requirements fail,
and `2` for input, profile, or output errors. `--minimum-score` and `--fail-on`
override gate thresholds for one invocation. See the
[dataset quality workflow](quality-workflow.md) for result and profile schemas.

Folder discovery is deterministic and scans one level deep by default; pass
`--recursive` (`-r`) to descend into subdirectories. Supported suffixes are
`.gpkg`, `.shp`, `.geojson`, `.json`, and `.parquet`. Worker selection is
automatic and memory-aware; `--workers` cannot override the safety ceiling.
See [parallel streaming audits](parallel-streaming.md) for scheduling,
progress, compatibility, and limitations.

### Audit benchmarking

Benchmarking is disabled by default. Enable it with `--benchmark` and select an
HTML, JSON, or Markdown report through `--benchmark-output`:

```bash
geoqc audit data/ --benchmark --benchmark-output benchmark.html
```

Use `--workers` and `--chunk-size` to configure the audit; their effective
values are included in every benchmark record. See the
[benchmark system guide](benchmark-system.md) for metric semantics, output
schemas, visualizations, and overhead notes.

### Road-network repair

Repair a projected road dataset without modifying the source:

```bash
geoqc repair-roads roads.shp repaired.gpkg \
  --snap-tolerance 0.1 \
  --output-layer roads_fixed \
  --report topology-report.json
```

The default snap tolerance is `0`, so exact intersections are noded without
moving endpoints. Set a tolerance in CRS units to close small digitizing gaps.
Inputs may be Shapefile, GeoJSON, FlatGeobuf, or GeoPackage; output is an atomic
GeoPackage write. Use `--layer NAME` for a multi-layer input GeoPackage and
`--overwrite` only when replacing an existing output intentionally. The command
rejects null/empty/non-line geometries, unknown CRS, accidental source overwrite,
and nonzero snapping in geographic coordinates unless `--allow-geographic` is
explicitly requested. Use `--max-features` to control the in-memory safety cap.
