"""Tests for bounded profiling and automatic dispatch observability."""

import logging
from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pytest
from shapely.geometry import Point

from geoqc.application.engine_selection import (
    GEOPANDAS_ENGINE,
    DatasetProfile,
    EngineDecision,
    EngineDecisionService,
)
from geoqc.application.ports.streaming import ChunkReader
from geoqc.application.streaming.geometry import GeometryAuditResult
from geoqc.application.streaming.models import DatasetMetadata, DatasetSource, FeatureChunk
from geoqc.infrastructure.gis.automatic_geometry_engine import AutomaticGeometryEngine
from geoqc.infrastructure.gis.engine_selection import DatasetProfiler


class _Reader:
    def __init__(self) -> None:
        self.requested_chunk_sizes: list[int] = []

    def inspect(self, source: DatasetSource) -> DatasetMetadata:
        return DatasetMetadata("GeoJSON", None, "EPSG:4326", 1, "geometry")

    def supports(self, source: DatasetSource) -> bool:
        return True

    def iter_chunks(self, source: DatasetSource, chunk_size: int) -> Iterator[FeatureChunk]:
        self.requested_chunk_sizes.append(chunk_size)
        yield FeatureChunk(0, pa.record_batch({"geometry": [Point(1, 2).wkb]}), 1)


class _Profiler:
    def profile(
        self,
        source: DatasetSource,
        reader: ChunkReader,
        metadata: DatasetMetadata,
    ) -> DatasetProfile:
        return DatasetProfile("GeoJSON", 2, 1, 512, 1_000_000_000)


class _StreamingDecisionService:
    def select(self, profile: DatasetProfile) -> EngineDecision:
        return EngineDecisionService().select(
            DatasetProfile("GeoJSON", 600_000_000, 1, 512, 1_000_000_000)
        )


def test_profiler_reads_only_bounded_sample(tmp_path: Path) -> None:
    path = tmp_path / "sample.geojson"
    path.write_text("{}", encoding="utf-8")
    reader = _Reader()
    profile = DatasetProfiler().profile(DatasetSource(path), reader)
    assert reader.requested_chunk_sizes == [256]
    assert profile.geometry.sampled_features == 1
    assert profile.geometry.average_vertices == 1


def test_automatic_engine_logs_selection_and_returns_contract(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "sample.geojson"
    path.write_text("{}", encoding="utf-8")
    reader = _Reader()
    with caplog.at_level(logging.INFO):
        result, decision = AutomaticGeometryEngine(
            reader,
            profiler=_Profiler(),  # type: ignore[arg-type]
            decision_service=_StreamingDecisionService(),  # type: ignore[arg-type]
        ).run(DatasetSource(path))
    assert decision.engine != GEOPANDAS_ENGINE
    assert isinstance(result, GeometryAuditResult)
    assert "engine=streaming" in caplog.text
