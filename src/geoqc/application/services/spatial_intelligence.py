"""Use cases for spatial intelligence workflows."""

from collections.abc import Sequence

from geoqc.application.ports.spatial_intelligence import (
    BoundarySnapper,
    RoadNetworkAnalyzer,
    RoadNetworkRepairer,
    SmallPolygonAnalyzer,
)
from geoqc.domain.models.spatial_intelligence import (
    BoundarySnapConfig,
    BoundarySnapResult,
    RoadNetworkConfig,
    RoadNetworkRepairConfig,
    RoadNetworkRepairResult,
    RoadNetworkReport,
    SmallPolygonConfig,
    SmallPolygonReport,
)


class BoundarySnapService:
    def __init__(self, engine: BoundarySnapper) -> None:
        self._engine = engine

    def preview(
        self, wkts: Sequence[str], config: BoundarySnapConfig | None = None
    ) -> BoundarySnapResult:
        return self._engine.snap(wkts, config or BoundarySnapConfig())


class RoadNetworkService:
    def __init__(self, engine: RoadNetworkAnalyzer) -> None:
        self._engine = engine

    def analyze(
        self, wkts: Sequence[str], config: RoadNetworkConfig | None = None
    ) -> RoadNetworkReport:
        return self._engine.analyze(wkts, config or RoadNetworkConfig())


class RoadNetworkRepairService:
    def __init__(self, engine: RoadNetworkRepairer) -> None:
        self._engine = engine

    def repair(
        self, wkts: Sequence[str], config: RoadNetworkRepairConfig | None = None
    ) -> RoadNetworkRepairResult:
        return self._engine.repair(wkts, config or RoadNetworkRepairConfig())


class SmallPolygonService:
    def __init__(self, engine: SmallPolygonAnalyzer) -> None:
        self._engine = engine

    def preview(
        self, wkts: Sequence[str], config: SmallPolygonConfig | None = None
    ) -> SmallPolygonReport:
        return self._engine.analyze(wkts, config or SmallPolygonConfig())
