from pathlib import Path

import pytest

from geoqc.application.streaming.models import DatasetSource
from geoqc.domain.exceptions import UnsupportedDatasetFormatError
from geoqc.infrastructure.gis.streaming import default_reader_registry
from geoqc.infrastructure.gis.streaming.parquet_reader import GeoParquetChunkReader
from geoqc.infrastructure.gis.streaming.pyogrio_reader import PyogrioChunkReader
from geoqc.infrastructure.gis.streaming.registry import ReaderRegistry


@pytest.mark.parametrize("suffix", [".gpkg", ".shp", ".geojson", ".json"])
def test_ogr_reader_supports_required_formats(suffix: str) -> None:
    assert PyogrioChunkReader().supports(DatasetSource(Path(f"dataset{suffix}")))


@pytest.mark.parametrize("suffix", [".parquet", ".geoparquet"])
def test_parquet_reader_supports_required_formats(suffix: str) -> None:
    assert GeoParquetChunkReader().supports(DatasetSource(Path(f"dataset{suffix}")))


def test_registry_is_extensible_and_default_registry_selects_required_readers() -> None:
    registry = ReaderRegistry()
    reader = PyogrioChunkReader()
    registry.register(reader)
    assert registry.resolve(DatasetSource(Path("roads.gpkg"))) is reader
    assert isinstance(
        default_reader_registry().resolve(DatasetSource(Path("roads.parquet"))),
        GeoParquetChunkReader,
    )
    with pytest.raises(UnsupportedDatasetFormatError):
        registry.resolve(DatasetSource(Path("roads.csv")))
