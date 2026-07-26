"""Shapely adapters for boundary, road, and small-polygon intelligence."""

import math
from collections.abc import Sequence

import shapely
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from geoqc.domain.models.spatial_intelligence import (
    BoundarySnapConfig,
    BoundarySnapFeature,
    BoundarySnapResult,
    Recommendation,
    RoadFinding,
    RoadIssueType,
    RoadNetworkConfig,
    RoadNetworkReport,
    SmallPolygonConfig,
    SmallPolygonFinding,
    SmallPolygonIssueType,
    SmallPolygonReport,
)


def _loads(wkts: Sequence[str]) -> list[BaseGeometry]:
    return [shapely.from_wkt(value) for value in wkts]


def _wkt(geometry: BaseGeometry) -> str:
    return str(shapely.to_wkt(geometry, rounding_precision=-1))


class ShapelyBoundarySnapper:
    """Snap nearby polygon vertices while enforcing strict safety limits."""

    def snap(self, geometries_wkt: Sequence[str], config: BoundarySnapConfig) -> BoundarySnapResult:
        original = _loads(geometries_wkt)
        if any(g.geom_type not in {"Polygon", "MultiPolygon"} for g in original):
            raise ValueError("boundary snap accepts only Polygon and MultiPolygon geometries")
        tree = STRtree(original)
        neighbours: list[set[int]] = [set() for _ in original]
        pairs: set[tuple[int, int]] = set()
        for index, geometry in enumerate(original):
            for candidate in tree.query(geometry.buffer(config.tolerance)):
                other = int(candidate)
                if other <= index:
                    continue
                distance = geometry.boundary.distance(original[other].boundary)
                if 0 < distance <= config.tolerance and not geometry.intersects(original[other]):
                    pairs.add((index, other))
                    # Move only the later feature toward a stable earlier anchor.
                    # Symmetric snapping can make both polygons cross the gap and overlap.
                    neighbours[other].add(index)

        output: list[BoundarySnapFeature] = []
        for index, before in enumerate(original):
            references = [original[item].boundary for item in sorted(neighbours[index])]
            candidate = before
            for reference in references:
                candidate = shapely.snap(candidate, reference, config.tolerance)
            output.append(
                self._assess(index, before, candidate, neighbours[index], original, config)
            )
        return BoundarySnapResult(tuple(output), len(pairs))

    def _assess(
        self,
        index: int,
        before: BaseGeometry,
        after: BaseGeometry,
        neighbours: set[int],
        all_geometries: Sequence[BaseGeometry],
        config: BoundarySnapConfig,
    ) -> BoundarySnapFeature:
        area_before = before.area
        area_after = after.area
        shift = before.hausdorff_distance(after)
        relative = abs(area_after - area_before) / max(area_before, 1e-15)
        max_shift = (
            config.max_shape_shift if config.max_shape_shift is not None else config.tolerance
        )
        reason = ""
        if after.equals_exact(before, 0):
            reason = "no eligible vertex was within tolerance"
        elif (
            after.is_empty
            or not after.is_valid
            or after.geom_type not in {"Polygon", "MultiPolygon"}
        ):
            reason = "candidate is not a valid polygon"
        elif shift > max_shift:
            reason = "shape shift exceeds configured limit"
        elif relative > config.max_relative_area_change:
            reason = "relative area change exceeds configured limit"
        else:
            for other_index, other in enumerate(all_geometries):
                if other_index == index:
                    continue
                overlap_before = before.intersection(other).area
                overlap_after = after.intersection(other).area
                if overlap_after - overlap_before > 1e-12:
                    reason = "candidate creates or increases an overlap"
                    break
        accepted = not reason
        final = after if accepted else before
        return BoundarySnapFeature(
            index,
            "repaired" if accepted else "unchanged",
            _wkt(before),
            _wkt(final),
            area_before,
            final.area,
            before.hausdorff_distance(final),
            tuple(sorted(neighbours)) if accepted else (),
            reason,
        )


class ShapelyRoadNetworkAnalyzer:
    """Analyze line endpoint topology without an external graph dependency."""

    def analyze(
        self, geometries_wkt: Sequence[str], config: RoadNetworkConfig
    ) -> RoadNetworkReport:
        geometries = _loads(geometries_wkt)
        if any(g.geom_type not in {"LineString", "MultiLineString"} for g in geometries):
            raise ValueError("road analyzer accepts only line geometries")
        lines = [self._representative_line(g) for g in geometries]
        findings: list[RoadFinding] = []
        endpoint_records = [(index, Point(line.coords[0])) for index, line in enumerate(lines)] + [
            (index, Point(line.coords[-1])) for index, line in enumerate(lines)
        ]
        endpoints = [point for _, point in endpoint_records]
        endpoint_tree = STRtree(endpoints)
        line_tree = STRtree(lines)

        for index, point in endpoint_records:
            degree = sum(
                point.distance(endpoints[int(candidate)]) <= config.duplicate_tolerance
                for candidate in endpoint_tree.query(point.buffer(config.duplicate_tolerance))
            )
            if degree == 1:
                findings.append(
                    RoadFinding(
                        RoadIssueType.DEAD_END, (index,), _wkt(point), "Endpoint has degree one"
                    )
                )
                if lines[index].length <= config.dangling_length_threshold:
                    findings.append(
                        RoadFinding(
                            RoadIssueType.DANGLING_ROAD,
                            (index,),
                            _wkt(point),
                            "Short road terminates without a connection",
                            lines[index].length,
                        )
                    )
                near = []
                for candidate in line_tree.query(point.buffer(config.connection_tolerance)):
                    other_index = int(candidate)
                    distance = point.distance(lines[other_index])
                    if other_index != index and 0 < distance <= config.connection_tolerance:
                        near.append((other_index, distance))
                if near:
                    target, distance = min(near, key=lambda item: item[1])
                    findings.append(
                        RoadFinding(
                            RoadIssueType.BROKEN_CONNECTION,
                            (index, target),
                            _wkt(point),
                            "Endpoint nearly touches another segment",
                            distance,
                        )
                    )

        for left, line in enumerate(lines):
            if line.is_ring and line.length <= config.max_loop_length:
                findings.append(
                    RoadFinding(
                        RoadIssueType.LOOP_ERROR,
                        (left,),
                        _wkt(line.centroid),
                        "Unexpected short closed loop",
                        line.length,
                    )
                )
            for candidate in line_tree.query(line.buffer(config.duplicate_tolerance)):
                right = int(candidate)
                if right <= left:
                    continue
                other = lines[right]
                distance = line.hausdorff_distance(other)
                overlap = line.buffer(max(config.duplicate_tolerance, 1e-12)).intersection(
                    other
                ).length / max(min(line.length, other.length), 1e-15)
                if (
                    distance <= config.duplicate_tolerance
                    and overlap >= config.duplicate_overlap_ratio
                ):
                    findings.append(
                        RoadFinding(
                            RoadIssueType.DUPLICATE_SEGMENT,
                            (left, right),
                            _wkt(line.centroid),
                            "Segments have duplicate geometry",
                            overlap,
                        )
                    )
        unique = {(f.issue_type, f.feature_indices, f.location_wkt): f for f in findings}
        ordered = tuple(
            sorted(
                unique.values(),
                key=lambda f: (f.issue_type.value, f.feature_indices, f.location_wkt),
            )
        )
        return RoadNetworkReport(len(geometries), ordered)

    @staticmethod
    def _representative_line(geometry: BaseGeometry) -> LineString:
        if isinstance(geometry, LineString):
            return geometry
        assert isinstance(geometry, MultiLineString)
        return max(geometry.geoms, key=lambda item: item.length)


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
