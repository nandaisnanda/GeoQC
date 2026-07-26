# GeoParquet optimization

GeoQC reads GeoParquet through the Arrow Dataset scanner and writes it one
Arrow batch at a time. The implementation avoids constructing a complete
`GeoDataFrame`, keeps memory bounded by batch and row-group sizes, and remains
compatible with the existing Streaming Engine.

## Why GeoParquet

| Format | Strength | Limitation for analytical scans |
| --- | --- | --- |
| GeoParquet | Columnar, compressed, typed, row-group statistics | Some desktop GIS interoperability is newer |
| GeoPackage | Portable multi-layer SQLite container | Row-oriented; projection still incurs database/OGR work |
| GeoJSON | Human-readable and web-friendly | Large, repeated keys, text parsing, weak typing |
| Shapefile | Broad legacy compatibility | Multi-file, field/type limits, no modern columnar pruning |

GeoParquet is normally the best choice for repeated QC scans because Arrow can
read only selected columns and Parquet can eliminate row groups using stored
statistics. Results depend on data distribution, compression, hardware, and
row-group layout; run the included benchmark for your workload.

## Lazy projected and filtered reads

`DatasetSource.scan` carries backend-neutral hints. The GeoParquet adapter
translates them into Arrow projection and filter expressions before any record
batch is yielded.

```python
from pathlib import Path

from geoqc.application.streaming import (
    DatasetSource,
    ScanOptions,
    ScanPredicate,
)
from geoqc.infrastructure.gis.streaming import default_reader_registry

source = DatasetSource(
    Path("roads.parquet"),
    scan=ScanOptions(
        columns=("road_id", "status"),
        predicates=(
            ScanPredicate("status", "==", "active"),
            ScanPredicate("quality_score", ">=", 80),
        ),
        include_geometry=True,
    ),
)
reader = default_reader_registry().resolve(source)

for chunk in reader.iter_chunks(source, chunk_size=65_536):
    # chunk.features is a pyarrow.RecordBatch, not a full GeoDataFrame.
    process(chunk)
```

Supported operators are `==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `not in`,
`is null`, and `is not null`. Predicates are combined with AND. Predicate
columns do not need to be output columns. Set `include_geometry=False` for
attribute-only rules to avoid reading WKB entirely.

Without `ScanOptions`, GeoQC preserves the original full-column behavior.
With scan options but no explicit `columns`, GeoQC reads only geometry by
default. Invalid columns and malformed datasets fail before processing.

## Bounded, atomic writes

```python
from pathlib import Path

from geoqc.infrastructure.gis.streaming import (
    GeoParquetStreamWriter,
    GeoParquetWriteOptions,
)

result = GeoParquetStreamWriter().write(
    Path("validated.parquet"),
    chunks,  # iterable of FeatureChunk, pyarrow.RecordBatch, or pyarrow.Table
    GeoParquetWriteOptions(
        geometry_column="geometry",
        crs={"id": {"authority": "EPSG", "code": 4326}},
        geometry_types=("Point",),
        compression="zstd",
        row_group_size=65_536,
        overwrite=False,
    ),
)
```

The writer emits GeoParquet 1.1 metadata with WKB geometry, requires a stable
Arrow schema, writes to a same-directory temporary file, and publishes with an
atomic replace only after success. It removes partial output after failures and
refuses accidental overwrite by default. Empty streams are rejected because
they provide no schema; callers that need an empty dataset should provide an
explicit schema using a dedicated upstream policy.

## Production tuning

- Start with `chunk_size=row_group_size=65_536`. Smaller values reduce peak
  latency/memory; larger values can improve throughput and compression.
- Keep `write_statistics=True`; predicate pushdown depends on useful row-group
  statistics. Sort or cluster frequently filtered columns before writing when
  practical.
- Select only columns required by the active rules. Geometry WKB is often the
  largest column.
- Keep `fragment_readahead` conservative for bounded memory. Increase
  `batch_readahead` only after measuring storage latency and RSS.
- Arrow allocations occur outside Python's object heap; production monitoring
  should observe process RSS in addition to `tracemalloc`.
- Atomic replacement protects readers on local filesystems. Validate object
  store semantics separately before adapting this local-path writer.

## Benchmark

The reproducible harness creates equivalent GeoPackage, GeoJSON, Shapefile,
and GeoParquet datasets and reports elapsed time, rows/second, peak Python
memory, and storage size. It also measures a projected and filtered
GeoParquet scan.

```bash
uv run python benchmarks/geoparquet_io.py --rows 250000
uv run python benchmarks/geoparquet_io.py --rows 250000 --json
```

Use multiple warm and cold runs on production-like disks. Do not treat one
machine's numbers as universal guarantees.