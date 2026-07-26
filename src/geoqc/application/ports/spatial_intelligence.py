"""Ports for spatial intelligence engines."""

from collections.abc import Sequence
from typing import Protocol

from geoqc.domain.models.spatial_intelligence import (
    BoundarySnapConfig,
    BoundarySnapResult,
    RoadNetworkConfig,
    RoadNetworkReport,
    SmallPolygonConfig,
    SmallPolygonReport,
)


class BoundarySnapper(Protocol):
    def snap(
        self, geometries_wkt: Sequence[str], config: BoundarySnapConfig
    ) -> BoundarySnapResult: ...


class RoadNetworkAnalyzer(Protocol):
    def analyze(
        self, geometries_wkt: Sequence[str], config: RoadNetworkConfig
    ) -> RoadNetworkReport: ...


class SmallPolygonAnalyzer(Protocol):
    def analyze(
        self, geometries_wkt: Sequence[str], config: SmallPolygonConfig
    ) -> SmallPolygonReport: ...
