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

## Planned commands

Subcommands that drive the CRS scanner, datum-shift detector, axis-order
detector, and HTML report renderer directly from the terminal are tracked in
[the roadmap](roadmap.md) and are not yet available.
Until then, use those building blocks as a library (see
[docs/index.md](index.md) for the full list of modules) or through the
optional [FastAPI service](api.md).
