"""Production streaming reader adapters."""

from geoqc.infrastructure.gis.streaming.parquet_reader import GeoParquetChunkReader
from geoqc.infrastructure.gis.streaming.parquet_writer import (
    GeoParquetStreamWriter,
    GeoParquetWriteOptions,
    GeoParquetWriteResult,
)
from geoqc.infrastructure.gis.streaming.pyogrio_reader import PyogrioChunkReader
from geoqc.infrastructure.gis.streaming.registry import ReaderRegistry


def default_reader_registry() -> ReaderRegistry:
    """Build the standard registry in explicit precedence order."""
    return ReaderRegistry((GeoParquetChunkReader(), PyogrioChunkReader()))


__all__ = [
    "GeoParquetChunkReader",
    "GeoParquetStreamWriter",
    "GeoParquetWriteOptions",
    "GeoParquetWriteResult",
    "PyogrioChunkReader",
    "ReaderRegistry",
    "default_reader_registry",
]
