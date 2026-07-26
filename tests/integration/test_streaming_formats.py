from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import pytest
from shapely.geometry import Point, Polygon

from geoqc.application.streaming.engine import StreamingEngine
from geoqc.application.streaming.geometry import (
    GeometryAuditResult,
    GeometryResultCollector,
)
from geoqc.application.streaming.models import DatasetSource, StreamingConfig, StreamingResult
from geoqc.infrastructure.gis.shapely_geometry_validator import ShapelyGeometryValidator
from geoqc.infrastructure.gis.streaming import default_reader_registry
from geoqc.infrastructure.gis.streaming.geometry_processor import GeometryChunkProcessor


@pytest.mark.parametrize(
    ("suffix", "driver"),
    [(".gpkg", "GPKG"), (".shp", "ESRI Shapefile"), (".geojson", "GeoJSON")],
)
def test_streams_required_ogr_formats_in_multiple_chunks(
    tmp_path: Path, suffix: str, driver: str
) -> None:
    source_path = tmp_path / f"features{suffix}"
    frame = gpd.GeoDataFrame(
        {"name": ["a", "b", "c"]},
        geometry=[Point(0, 0), Point(1, 1), Point(2, 2)],
        crs="EPSG:4326",
    )
    frame.to_file(source_path, driver=driver)

    result = _run(source_path)

    assert result.feature_count == 3
    assert result.chunk_count == 2
    assert isinstance(result.result, GeometryAuditResult)
    assert result.result.invalid_feature_count == 0


def test_streams_geoparquet_and_matches_legacy_geometry_results(tmp_path: Path) -> None:
    source_path = tmp_path / "features.parquet"
    bowtie = Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])
    frame = gpd.GeoDataFrame(geometry=[Point(0, 0), bowtie, None], crs="EPSG:4326")
    frame.to_parquet(source_path)

    execution = _run(source_path)
    audit = execution.result
    assert isinstance(audit, GeometryAuditResult)

    validator = ShapelyGeometryValidator()
    legacy = [
        validator.validate(geometry) if geometry is not None else None
        for geometry in frame.geometry
    ]
    legacy_invalid = sum(result is None or not result.is_valid for result in legacy)
    assert audit.feature_count == len(frame)
    assert audit.invalid_feature_count == legacy_invalid
    assert [finding.feature_index for finding in audit.findings] == [1, 2]


def _run(path: Path) -> StreamingResult:
    source = DatasetSource(path)
    return StreamingEngine(
        default_reader_registry().resolve(source),
        GeometryChunkProcessor(ShapelyGeometryValidator()),
        GeometryResultCollector(),
        StreamingConfig(chunk_size=2, minimum_chunk_size=1),
    ).run(source)
