"""Row-batch streaming for GeoParquet datasets."""

import json
from collections.abc import Iterator
from typing import Any

import pyarrow.dataset as ds  # type: ignore[import-untyped]
import pyarrow.parquet as parquet  # type: ignore[import-untyped]

from geoqc.application.streaming.models import (
    DatasetMetadata,
    DatasetSource,
    FeatureChunk,
    ScanPredicate,
)
from geoqc.domain.exceptions import CorruptDatasetError, DatasetEncodingError


class GeoParquetChunkReader:
    """Read GeoParquet record batches without constructing a full GeoDataFrame."""

    def supports(self, source: DatasetSource) -> bool:
        return source.path.suffix.casefold() in {".parquet", ".geoparquet"}

    def inspect(self, source: DatasetSource) -> DatasetMetadata:
        try:
            file = parquet.ParquetFile(source.path)
            geo = _geo_metadata(file.metadata.metadata)
            primary = str(geo.get("primary_column", "geometry"))
            columns = geo.get("columns", {})
            column = columns.get(primary, {}) if isinstance(columns, dict) else {}
            crs_value = column.get("crs") if isinstance(column, dict) else None
            crs = json.dumps(crs_value, sort_keys=True) if crs_value else None
            return DatasetMetadata(
                driver="GeoParquet",
                layer=None,
                crs=crs,
                feature_count=file.metadata.num_rows,
                geometry_column=primary,
                encoding="UTF-8",
            )
        except UnicodeError as error:
            raise DatasetEncodingError(f"Cannot decode metadata in {source.path!s}") from error
        except Exception as error:
            raise CorruptDatasetError(f"Cannot inspect GeoParquet {source.path!s}") from error

    def iter_chunks(self, source: DatasetSource, chunk_size: int) -> Iterator[FeatureChunk]:
        offset = 0
        try:
            metadata = self.inspect(source)
            dataset = ds.dataset(source.path, format="parquet")
            columns = _projected_columns(source, metadata.geometry_column, dataset.schema.names)
            expression = _filter_expression(source.scan.predicates if source.scan else ())
            scan = source.scan
            scanner = dataset.scanner(
                columns=columns,
                filter=expression,
                batch_size=chunk_size,
                use_threads=scan.use_threads if scan else True,
                batch_readahead=scan.batch_readahead if scan else 4,
                fragment_readahead=scan.fragment_readahead if scan else 1,
            )
            for batch in scanner.to_batches():
                size = len(batch)
                if size:
                    yield FeatureChunk(offset=offset, features=batch, size=size)
                    offset += size
        except UnicodeError as error:
            raise DatasetEncodingError(f"Cannot decode GeoParquet {source.path!s}") from error
        except MemoryError:
            raise
        except Exception as error:
            raise CorruptDatasetError(f"Cannot stream GeoParquet {source.path!s}") from error


def _geo_metadata(metadata: dict[bytes, bytes] | None) -> dict[str, Any]:
    if not metadata or b"geo" not in metadata:
        raise ValueError("Parquet file has no GeoParquet metadata")
    value = json.loads(metadata[b"geo"].decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Invalid GeoParquet metadata")
    return value


def _projected_columns(
    source: DatasetSource, geometry_column: str, available: list[str]
) -> list[str] | None:
    if source.scan is None or source.scan.columns is None:
        return [geometry_column] if source.scan and source.scan.include_geometry else None
    columns = list(source.scan.columns)
    if source.scan.include_geometry and geometry_column not in columns:
        columns.append(geometry_column)
    missing = sorted(set(columns).difference(available))
    if missing:
        raise ValueError(f"Unknown GeoParquet columns: {', '.join(missing)}")
    return columns


def _filter_expression(predicates: tuple[ScanPredicate, ...]) -> ds.Expression | None:
    expression: ds.Expression | None = None
    for predicate in predicates:
        field = ds.field(predicate.column)
        value = predicate.value
        if predicate.operator == "==":
            current = field == value
        elif predicate.operator == "!=":
            current = field != value
        elif predicate.operator == "<":
            current = field < value
        elif predicate.operator == "<=":
            current = field <= value
        elif predicate.operator == ">":
            current = field > value
        elif predicate.operator == ">=":
            current = field >= value
        elif predicate.operator == "in":
            current = field.isin(value)
        elif predicate.operator == "not in":
            current = ~field.isin(value)
        elif predicate.operator == "is null":
            current = field.is_null()
        else:
            current = ~field.is_null()
        expression = current if expression is None else expression & current
    return expression
