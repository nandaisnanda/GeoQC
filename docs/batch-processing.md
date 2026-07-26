# Batch Processing

`BatchProcessor` is a generic use case for running one processor over many
local datasets. It accepts files, folders, or a mix of both, and does not
depend on Shapely, Pyogrio, Typer, or any specific QC implementation.

## Dataset discovery

Recognized extensions by default:

- `.fgb`
- `.geojson`
- `.gml`
- `.gpkg`
- `.json`
- `.kml`
- `.parquet`
- `.shp`

Extension matching is case-insensitive. Discovered files are converted to
absolute paths, deduplicated, and sorted so batch results are deterministic.
Folders are scanned one level deep by default; pass `recursive=True` to
include subfolders.

An explicit file input with an unsupported extension raises `ValueError`; a
path that does not exist raises `FileNotFoundError`. Unsupported files found
inside a folder are skipped.

## Running a batch

A processor is any callable that accepts a `pathlib.Path` and returns a
result of any type:

```python
from pathlib import Path

from geoqc.application.services import BatchProcessor
from geoqc.interfaces.cli.progress import ConsoleProgressIndicator


def inspect_dataset(path: Path) -> str:
    # Wire this to a geometry validator, attribute scanner, or QC pipeline.
    return path.name


batch = BatchProcessor(inspect_dataset)
result = batch.process(
    ["data/roads.gpkg", "data/regencies"],
    recursive=True,
    progress=ConsoleProgressIndicator(),
)

print(result.total, result.succeeded, result.failed)
```

A processor failure is captured per dataset as `BatchItemStatus.FAILED`; the
next dataset is still processed. `BatchResult` exposes `total`, `succeeded`,
`failed`, and `is_successful`.

## Progress events

An observer receives `BatchProgress`:

1. an initial event `(completed=0, total=N)` once discovery finishes;
2. one event after each file is processed, including its source and status.

`ConsoleProgressIndicator` is a simple terminal adapter. Other interfaces can
consume the same events for a web progress bar, telemetry, or an API
callback without changing the application layer.

## Custom extensions

The list of supported formats can be overridden at construction time. The
leading dot is optional and values are normalized:

```python
batch = BatchProcessor(inspect_dataset, supported_suffixes=["csv", ".zip"])
```
