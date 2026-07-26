"""Bounded-memory, atomic GeoParquet streaming writer."""

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as parquet  # type: ignore[import-untyped]

from geoqc.application.streaming.models import FeatureChunk


@dataclass(frozen=True, slots=True)
class GeoParquetWriteOptions:
    """Storage settings for an interoperable GeoParquet output."""

    geometry_column: str = "geometry"
    crs: dict[str, Any] | str | None = None
    geometry_types: tuple[str, ...] = ()
    compression: Literal["snappy", "gzip", "brotli", "zstd", "lz4", "none"] = "zstd"
    compression_level: int | None = None
    row_group_size: int = 65_536
    data_page_size: int = 1_048_576
    write_statistics: bool = True
    overwrite: bool = False

    def __post_init__(self) -> None:
        if not self.geometry_column:
            raise ValueError("geometry_column cannot be empty")
        if self.row_group_size < 1 or self.data_page_size < 1:
            raise ValueError("row_group_size and data_page_size must be positive")


@dataclass(frozen=True, slots=True)
class GeoParquetWriteResult:
    path: Path
    row_count: int
    chunk_count: int
    bytes_written: int


class GeoParquetStreamWriter:
    """Write Arrow batches incrementally and publish the file atomically."""

    def write(
        self,
        path: Path,
        chunks: Iterable[FeatureChunk | pa.RecordBatch | pa.Table],
        options: GeoParquetWriteOptions | None = None,
    ) -> GeoParquetWriteResult:
        settings = options or GeoParquetWriteOptions()
        path = Path(path)
        if path.exists() and not settings.overwrite:
            raise FileExistsError(f"Output already exists: {path!s}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        writer: parquet.ParquetWriter | None = None
        expected_schema: pa.Schema | None = None
        rows = chunks_written = 0
        try:
            for item in chunks:
                table = _as_table(item)
                if table.num_rows == 0:
                    continue
                if writer is None:
                    schema = _with_geo_metadata(table.schema, settings)
                    if settings.geometry_column not in schema.names:
                        raise ValueError(
                            f"Geometry column {settings.geometry_column!r} is absent from schema"
                        )
                    writer = parquet.ParquetWriter(
                        temporary,
                        schema,
                        compression=(
                            None if settings.compression == "none" else settings.compression
                        ),
                        compression_level=settings.compression_level,
                        data_page_size=settings.data_page_size,
                        write_statistics=settings.write_statistics,
                    )
                    expected_schema = table.schema.remove_metadata()
                elif table.schema.remove_metadata() != expected_schema:
                    raise ValueError("All GeoParquet chunks must have the same Arrow schema")
                writer.write_table(table, row_group_size=settings.row_group_size)
                rows += table.num_rows
                chunks_written += 1
            if writer is None:
                raise ValueError("Cannot write GeoParquet from an empty chunk stream")
            writer.close()
            writer = None
            os.replace(temporary, path)
            return GeoParquetWriteResult(path, rows, chunks_written, path.stat().st_size)
        except Exception:
            if writer is not None:
                writer.close()
            temporary.unlink(missing_ok=True)
            raise


def _as_table(item: FeatureChunk | pa.RecordBatch | pa.Table) -> pa.Table:
    features = item.features if isinstance(item, FeatureChunk) else item
    if isinstance(features, pa.Table):
        return features
    if isinstance(features, pa.RecordBatch):
        return pa.Table.from_batches([features])
    raise TypeError("GeoParquet writer accepts FeatureChunk, RecordBatch, or Table values")


def _with_geo_metadata(schema: pa.Schema, options: GeoParquetWriteOptions) -> pa.Schema:
    crs: Any = options.crs
    if isinstance(crs, str):
        try:
            crs = json.loads(crs)
        except json.JSONDecodeError:
            crs = crs
    column: dict[str, Any] = {"encoding": "WKB"}
    if crs is not None:
        column["crs"] = crs
    if options.geometry_types:
        column["geometry_types"] = list(options.geometry_types)
    geo = {
        "version": "1.1.0",
        "primary_column": options.geometry_column,
        "columns": {options.geometry_column: column},
    }
    metadata = dict(schema.metadata or {})
    metadata[b"geo"] = json.dumps(geo, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return schema.with_metadata(metadata)
