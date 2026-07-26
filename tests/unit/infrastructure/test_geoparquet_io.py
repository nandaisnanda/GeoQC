import json
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as parquet  # type: ignore[import-untyped]
import pytest

from geoqc.application.streaming import DatasetSource, ScanOptions, ScanPredicate
from geoqc.infrastructure.gis.streaming.parquet_reader import GeoParquetChunkReader
from geoqc.infrastructure.gis.streaming.parquet_writer import (
    GeoParquetStreamWriter,
    GeoParquetWriteOptions,
)


def _batches() -> list[pa.RecordBatch]:
    return [
        pa.record_batch(
            [
                pa.array([1, 2, 3]),
                pa.array(["west", "east", "east"]),
                pa.array([b"a", b"b", b"c"]),
            ],
            names=["id", "region", "geometry"],
        ),
        pa.record_batch(
            [pa.array([4, 5]), pa.array(["west", "east"]), pa.array([b"d", b"e"])],
            names=["id", "region", "geometry"],
        ),
    ]


def test_writer_and_reader_round_trip_with_projection_and_pushdown(tmp_path: Path) -> None:
    path = tmp_path / "roads.parquet"
    result = GeoParquetStreamWriter().write(
        path,
        _batches(),
        GeoParquetWriteOptions(crs={"id": {"authority": "EPSG", "code": 4326}}, row_group_size=2),
    )
    assert (result.row_count, result.chunk_count) == (5, 2)
    assert result.bytes_written > 0

    reader = GeoParquetChunkReader()
    metadata = reader.inspect(DatasetSource(path))
    assert metadata.feature_count == 5
    assert metadata.geometry_column == "geometry"
    assert json.loads(metadata.crs or "null")["id"]["code"] == 4326

    source = DatasetSource(
        path,
        scan=ScanOptions(
            columns=("id",),
            predicates=(ScanPredicate("region", "==", "east"), ScanPredicate("id", ">", 2)),
        ),
    )
    chunks = list(reader.iter_chunks(source, chunk_size=1))
    table = pa.Table.from_batches([chunk.features for chunk in chunks])
    assert table.column_names == ["id", "geometry"]
    assert table["id"].to_pylist() == [3, 5]
    assert [chunk.offset for chunk in chunks] == [0, 1]


def test_reader_can_skip_geometry_for_attribute_only_scan(tmp_path: Path) -> None:
    path = tmp_path / "roads.parquet"
    GeoParquetStreamWriter().write(path, _batches())
    source = DatasetSource(path, scan=ScanOptions(columns=("region",), include_geometry=False))
    chunks = list(GeoParquetChunkReader().iter_chunks(source, chunk_size=10))
    assert chunks[0].features.schema.names == ["region"]


def test_writer_is_atomic_on_schema_failure(tmp_path: Path) -> None:
    path = tmp_path / "roads.parquet"
    incompatible = pa.record_batch([pa.array(["bad"])], names=["geometry"])
    with pytest.raises(ValueError, match="same Arrow schema"):
        GeoParquetStreamWriter().write(path, [*_batches(), incompatible])
    assert not path.exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_writer_refuses_overwrite_and_emits_geo_metadata(tmp_path: Path) -> None:
    path = tmp_path / "roads.parquet"
    writer = GeoParquetStreamWriter()
    writer.write(path, _batches())
    with pytest.raises(FileExistsError):
        writer.write(path, _batches())
    metadata = parquet.ParquetFile(path).metadata.metadata
    assert metadata is not None
    assert json.loads(metadata[b"geo"])["version"] == "1.1.0"


@pytest.mark.parametrize("operator", ["in", "not in"])
def test_collection_predicates_require_collection_values(operator: str) -> None:
    with pytest.raises(ValueError, match="requires a collection"):
        ScanPredicate("region", operator, "east")  # type: ignore[arg-type]
