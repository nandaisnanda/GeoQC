"""Parity test proving both execution paths produce the same geometry audit."""

from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
from shapely.geometry import LineString, Point

from geoqc.application.engine_selection import (
    DatasetProfile,
    EngineDecisionService,
    EngineSelectionConfig,
)
from geoqc.application.ports.streaming import ChunkReader
from geoqc.application.streaming.models import DatasetMetadata, DatasetSource
from geoqc.infrastructure.gis.automatic_geometry_engine import AutomaticGeometryEngine
from geoqc.infrastructure.gis.streaming import default_reader_registry


class _Profiler:
    def __init__(self, estimated_memory_bytes: int) -> None:
        self._estimated = estimated_memory_bytes

    def profile(
        self,
        source: DatasetSource,
        reader: ChunkReader,
        metadata: DatasetMetadata,
    ) -> DatasetProfile:
        return DatasetProfile(metadata.driver, source.path.stat().st_size, 3, self._estimated, None)


def test_geopandas_and_streaming_results_are_identical(tmp_path: Path) -> None:
    path = tmp_path / "parity.gpkg"
    frame = gpd.GeoDataFrame(
        {"name": ["valid", "duplicate", "missing"]},
        geometry=[Point(0, 0), LineString([(0, 0), (1, 1), (1, 1)]), None],
        crs="EPSG:4326",
    )
    frame.to_file(path, driver="GPKG", layer="features")
    source = DatasetSource(path, layer="features")
    reader = default_reader_registry().resolve(source)
    config = EngineSelectionConfig(maximum_memory_bytes=1_000)

    in_memory, in_memory_decision = AutomaticGeometryEngine(
        reader,
        profiler=_Profiler(1),  # type: ignore[arg-type]
        decision_service=EngineDecisionService(config),
    ).run(source)
    streamed, streaming_decision = AutomaticGeometryEngine(
        reader,
        profiler=_Profiler(2_000),  # type: ignore[arg-type]
        decision_service=EngineDecisionService(config),
        chunk_size=1,
    ).run(source)

    assert in_memory_decision.engine == "geopandas"
    assert streaming_decision.engine == "streaming"
    assert in_memory == streamed
