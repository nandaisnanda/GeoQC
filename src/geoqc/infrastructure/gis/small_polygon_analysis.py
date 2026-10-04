"""Shapely small-polygon analysis adapter."""

import math
from collections.abc import Sequence

import shapely
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from geoqc.domain.models.spatial_intelligence import (
    Recommendation,
    SmallPolygonConfig,
    SmallPolygonFinding,
    SmallPolygonIssueType,
    SmallPolygonReport,
)
from geoqc.infrastructure.gis.spatial_helpers import _loads, _wkt


class ShapelySmallPolygonAnalyzer:
    """Classify small polygons and create non-mutating merge previews."""

    def analyze(
        self, geometries_wkt: Sequence[str], config: SmallPolygonConfig
    ) -> SmallPolygonReport:
        geometries = _loads(geometries_wkt)
        if any(g.geom_type not in {"Polygon", "MultiPolygon"} for g in geometries):
            raise ValueError("small polygon analyzer accepts only polygon geometries")
        tree = STRtree(geometries)
        findings: list[SmallPolygonFinding] = []
        for index, geometry in enumerate(geometries):
            perimeter = geometry.length
            compactness = (
                4 * math.pi * geometry.area / (perimeter * perimeter) if perimeter else 0.0
            )
            issue = self._classify(index, geometry, compactness, geometries, config)
            if issue is None:
                continue
            candidates = [
                int(item)
                for item in tree.query(geometry.buffer(config.merge_tolerance))
                if int(item) != index
            ]
            target = self._target(geometry, candidates, geometries)
            recommendation, preview, reason = self._recommend(
                geometry, target, geometries, issue, config
            )
            findings.append(
                SmallPolygonFinding(
                    index,
                    issue,
                    recommendation,
                    geometry.area,
                    compactness,
                    _wkt(geometry),
                    target,
                    _wkt(geometries[target]) if target is not None else None,
                    _wkt(preview) if preview is not None else None,
                    reason,
                )
            )
        return SmallPolygonReport(len(geometries), tuple(findings))

    @staticmethod
    def _classify(
        index: int,
        geometry: BaseGeometry,
        compactness: float,
        geometries: Sequence[BaseGeometry],
        config: SmallPolygonConfig,
    ) -> SmallPolygonIssueType | None:
        if geometry.area <= config.noise_area_threshold:
            return SmallPolygonIssueType.NOISE_GEOMETRY
        if (
            geometry.area <= config.sliver_area_threshold
            and compactness <= config.sliver_compactness_threshold
        ):
            return SmallPolygonIssueType.SLIVER_POLYGON
        nearest = min(
            (
                geometry.distance(other)
                for other_index, other in enumerate(geometries)
                if other_index != index
            ),
            default=math.inf,
        )
        if (
            geometry.area <= config.tiny_island_area_threshold
            and nearest >= config.isolation_distance
        ):
            return SmallPolygonIssueType.TINY_ISLAND
        return None

    @staticmethod
    def _target(
        source: BaseGeometry, candidates: list[int], geometries: Sequence[BaseGeometry]
    ) -> int | None:
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda index: (
                source.boundary.intersection(geometries[index].boundary).length,
                -source.distance(geometries[index]),
                -index,
            ),
        )

    @staticmethod
    def _recommend(
        source: BaseGeometry,
        target: int | None,
        geometries: Sequence[BaseGeometry],
        issue: SmallPolygonIssueType,
        config: SmallPolygonConfig,
    ) -> tuple[Recommendation, BaseGeometry | None, str]:
        if target is not None:
            base = geometries[target]
            preview = shapely.union(base, source)
            relative = abs(preview.area - base.area) / max(base.area, 1e-15)
            if preview.is_valid and relative <= config.max_target_area_change:
                return Recommendation.MERGE, preview, "safe neighbouring polygon merge preview"
        if issue in {SmallPolygonIssueType.NOISE_GEOMETRY, SmallPolygonIssueType.TINY_ISLAND}:
            return Recommendation.DELETE, None, "no safe merge target; deletion recommended"
        return Recommendation.IGNORE, None, "no safe merge target; retain for manual review"
