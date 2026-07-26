"""Composition adapter dispatching geometry audits to the selected engine."""

import logging

from geoqc.application.engine_selection import (
    GEOPANDAS_ENGINE,
    EngineDecision,
    EngineDecisionService,
)
from geoqc.application.ports.streaming import ChunkReader
from geoqc.application.streaming.engine import StreamingEngine
from geoqc.application.streaming.geometry import GeometryAuditResult, GeometryResultCollector
from geoqc.application.streaming.models import DatasetSource, StreamingConfig
from geoqc.infrastructure.gis.engine_selection import DatasetProfiler
from geoqc.infrastructure.gis.geopandas_geometry_engine import GeoPandasGeometryEngine
from geoqc.infrastructure.gis.shapely_geometry_validator import ShapelyGeometryValidator
from geoqc.infrastructure.gis.streaming.geometry_processor import GeometryChunkProcessor

LOGGER = logging.getLogger(__name__)


class AutomaticGeometryEngine:
    """Profile, decide, log, and execute without changing the result contract."""

    def __init__(
        self,
        reader: ChunkReader,
        *,
        chunk_size: int = 16_384,
        maximum_findings: int = 1_000,
        profiler: DatasetProfiler | None = None,
        decision_service: EngineDecisionService | None = None,
    ) -> None:
        self._reader = reader
        self._chunk_size = chunk_size
        self._maximum_findings = maximum_findings
        self._profiler = profiler or DatasetProfiler()
        self._decision_service = decision_service or EngineDecisionService()

    def run(self, source: DatasetSource) -> tuple[GeometryAuditResult, EngineDecision]:
        metadata = self._reader.inspect(source)
        profile = self._profiler.profile(source, self._reader, metadata)
        decision = self._decision_service.select(profile)
        LOGGER.info(
            "Audit engine selected: engine=%s reasons=%s features=%s size_bytes=%d "
            "estimated_memory_bytes=%d available_memory_bytes=%s average_vertices=%.1f",
            decision.engine,
            "; ".join(decision.reasons),
            profile.feature_count,
            profile.size_bytes,
            profile.estimated_memory_bytes,
            profile.available_memory_bytes,
            profile.geometry.average_vertices,
        )
        if decision.engine == GEOPANDAS_ENGINE:
            result = GeoPandasGeometryEngine(self._maximum_findings).run(source)
        else:
            execution = StreamingEngine(
                self._reader,
                GeometryChunkProcessor(ShapelyGeometryValidator()),
                GeometryResultCollector(self._maximum_findings),
                StreamingConfig(
                    chunk_size=self._chunk_size,
                    minimum_chunk_size=min(256, self._chunk_size),
                ),
            ).run(source)
            result = execution.result
            if not isinstance(result, GeometryAuditResult):
                raise TypeError("Unexpected geometry audit result")
        return result, decision
