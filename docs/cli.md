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
| `geoqc check DATASET`         | Run unified profile-driven dataset QC.            | `0`/`1`/`2` |
| `geoqc repair-roads IN OUT`   | Snap and fully node a road layer into a new GPKG. | `0`/`2`   |
| `geoqc` (no args)             | Equivalent to `--help`.                          | `0`       |
| Unknown option                | Reject the invocation with a usage error.         | `2`       |

Example:

```console
$ geoqc --version
GeoQC 0.1.0
```

Exit codes follow the conventional Unix/Click meaning: `0` for success and
`2` for a command-line usage error (unknown option, missing argument, or an
input path that does not exist). Audit commands return `1` when any discovered
dataset fails; failures are isolated and remaining datasets continue. The
CLI disables pretty tracebacks (`pretty_exceptions_enable=False`) so
unexpected errors print a plain message instead of an internal stack trace.

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

## Planned commands

Subcommands that drive the CRS scanner, datum-shift detector, axis-order
detector, and HTML report renderer directly from the terminal are tracked in
[the roadmap](roadmap.md) and are not yet available.
Until then, use those building blocks as a library (see
[docs/index.md](index.md) for the full list of modules) or through the
optional [FastAPI service](api.md).
