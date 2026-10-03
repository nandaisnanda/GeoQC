"""Shapely adapters for boundary, road, and small-polygon intelligence."""

import math
from collections.abc import Sequence

import shapely
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points
from shapely.strtree import STRtree

from geoqc.domain.models.spatial_intelligence import (
    BoundarySnapConfig,
    BoundarySnapFeature,
    BoundarySnapResult,
    Recommendation,
    RoadFinding,
    RoadIssueType,
    RoadNetworkConfig,
    RoadNetworkRepairConfig,
    RoadNetworkRepairResult,
    RoadNetworkReport,
    RoadRepairSegment,
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
        lines: list[LineString] = []
        owners: list[int] = []
        for owner, geometry in enumerate(geometries):
            if isinstance(geometry, LineString):
                parts = [geometry]
            else:
                assert isinstance(geometry, MultiLineString)
                parts = list(geometry.geoms)
            for part in parts:
                if not part.is_empty:
                    lines.append(part)
                    owners.append(owner)
        findings: list[RoadFinding] = []
        endpoint_records = [
            (line_index, Point(line.coords[endpoint_index]))
            for line_index, line in enumerate(lines)
            for endpoint_index in (0, -1)
        ]
        endpoints = [point for _, point in endpoint_records]
        endpoint_tree = STRtree(endpoints)
        line_tree = STRtree(lines)

        for line_index, point in endpoint_records:
            connected_lines = {
                int(candidate)
                for candidate in line_tree.query(point.buffer(config.duplicate_tolerance))
                if int(candidate) != line_index
                and point.distance(lines[int(candidate)]) <= config.duplicate_tolerance
            }
            endpoint_degree = sum(
                point.distance(endpoints[int(candidate)]) <= config.duplicate_tolerance
                for candidate in endpoint_tree.query(point.buffer(config.duplicate_tolerance))
            )
            if not connected_lines and endpoint_degree == 1:
                owner = owners[line_index]
                findings.append(
                    RoadFinding(
                        RoadIssueType.DEAD_END, (owner,), _wkt(point), "Endpoint has degree one"
                    )
                )
                if lines[line_index].length <= config.dangling_length_threshold:
                    findings.append(
                        RoadFinding(
                            RoadIssueType.DANGLING_ROAD,
                            (owner,),
                            _wkt(point),
                            "Short road terminates without a connection",
                            lines[line_index].length,
                        )
                    )
                near = []
                for candidate in line_tree.query(point.buffer(config.connection_tolerance)):
                    other_index = int(candidate)
                    distance = point.distance(lines[other_index])
                    if (
                        other_index != line_index
                        and config.duplicate_tolerance < distance <= config.connection_tolerance
                    ):
                        near.append((other_index, distance))
                if near:
                    target, distance = min(near, key=lambda item: item[1])
                    findings.append(
                        RoadFinding(
                            RoadIssueType.BROKEN_CONNECTION,
                            tuple(sorted({owner, owners[target]})),
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
                        (owners[left],),
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
                intersection = line.intersection(other)
                for point in self._intersection_points(intersection):
                    if not (self._is_endpoint(line, point) and self._is_endpoint(other, point)):
                        findings.append(
                            RoadFinding(
                                RoadIssueType.UNNODED_INTERSECTION,
                                tuple(sorted({owners[left], owners[right]})),
                                _wkt(point),
                                "Intersection is not an endpoint of both segments",
                            )
                        )
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
                            tuple(sorted({owners[left], owners[right]})),
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
    def _intersection_points(geometry: BaseGeometry) -> list[Point]:
        if isinstance(geometry, Point):
            return [geometry]
        if geometry.geom_type in {"MultiPoint", "GeometryCollection"}:
            return [part for part in shapely.get_parts(geometry) if isinstance(part, Point)]
        return []

    @staticmethod
    def _is_endpoint(line: LineString, point: Point) -> bool:
        return (
            point.distance(Point(line.coords[0])) <= 1e-12
            or point.distance(Point(line.coords[-1])) <= 1e-12
        )


class ShapelyRoadNetworkRepairer:
    """Snap small endpoint gaps and node all road intersections.

    Output is intentionally segmented: every crossing and T-junction becomes a
    true graph node. Each segment records all source feature indices that cover
    it, so callers can restore attributes without relying on spatial guessing.
    """

    def repair(
        self, geometries_wkt: Sequence[str], config: RoadNetworkRepairConfig
    ) -> RoadNetworkRepairResult:
        geometries = _loads(geometries_wkt)
        if any(g.geom_type not in {"LineString", "MultiLineString"} for g in geometries):
            raise ValueError("road repair accepts only line geometries")
        if any(g.is_empty for g in geometries):
            raise ValueError("road repair does not accept empty geometries")

        parts: list[LineString] = []
        owners: list[int] = []
        for source_index, geometry in enumerate(geometries):
            if isinstance(geometry, LineString):
                source_parts = [geometry]
            else:
                assert isinstance(geometry, MultiLineString)
                source_parts = list(geometry.geoms)
            for part in source_parts:
                # GEOS topology is two-dimensional. Dropping Z also prevents
                # NaN/interpolated elevations at newly created intersections.
                cleaned = shapely.force_2d(shapely.remove_repeated_points(part, 0.0))
                if isinstance(cleaned, LineString) and cleaned.length > 0:
                    parts.append(cleaned)
                    owners.append(source_index)

        snapped, snapped_count = self._snap_endpoints(parts, config.snap_tolerance)
        noded = shapely.node(shapely.union_all(snapped))
        output = [
            part
            for part in shapely.get_parts(noded)
            if isinstance(part, LineString) and part.length >= config.minimum_segment_length
        ]
        output.sort(key=lambda line: (*line.bounds, _wkt(line)))
        provenance = self._provenance(output, snapped, owners, config.minimum_segment_length)
        segments = tuple(
            RoadRepairSegment(index, provenance[index], _wkt(line), float(line.length))
            for index, line in enumerate(output)
        )
        return RoadNetworkRepairResult(
            input_feature_count=len(geometries),
            input_part_count=len(parts),
            snapped_endpoint_count=snapped_count,
            segments=segments,
        )

    def _snap_endpoints(
        self, lines: Sequence[LineString], tolerance: float
    ) -> tuple[list[LineString], int]:
        if tolerance <= 0 or not lines:
            return list(lines), 0

        endpoints = [
            (line_index, endpoint_index, Point(line.coords[endpoint_index]))
            for line_index, line in enumerate(lines)
            for endpoint_index in (0, -1)
        ]
        endpoint_tree = STRtree([item[2] for item in endpoints])
        groups: list[list[int]] = []
        group_by_endpoint: dict[int, int] = {}
        for index, (line_index, _endpoint_index, point) in enumerate(endpoints):
            candidate_groups = {
                group_by_endpoint[int(candidate)]
                for candidate in endpoint_tree.query(point.buffer(tolerance))
                if int(candidate) < index
                and endpoints[int(candidate)][0] != line_index
                and int(candidate) in group_by_endpoint
            }
            selected: tuple[float, int] | None = None
            for group_index in sorted(candidate_groups):
                members = [*groups[group_index], index]
                if any(endpoints[item][0] == line_index for item in groups[group_index]):
                    continue
                radius = min(
                    max(endpoints[anchor][2].distance(endpoints[member][2]) for member in members)
                    for anchor in members
                )
                if radius <= tolerance and (selected is None or radius < selected[0]):
                    selected = (radius, group_index)
            if selected is None:
                group_by_endpoint[index] = len(groups)
                groups.append([index])
            else:
                group_index = selected[1]
                groups[group_index].append(index)
                group_by_endpoint[index] = group_index

        targets: dict[tuple[int, int], Point] = {}
        for group in groups:
            anchor_index = min(
                group,
                key=lambda candidate: (
                    max(endpoints[candidate][2].distance(endpoints[member][2]) for member in group),
                    sum(endpoints[candidate][2].distance(endpoints[member][2]) for member in group),
                    candidate,
                ),
            )
            anchor = endpoints[anchor_index][2]
            for endpoint_index in group:
                line_index, position, point = endpoints[endpoint_index]
                if not point.equals(anchor):
                    targets[(line_index, position)] = anchor

        clustered = [
            self._replace_endpoints(
                line,
                targets.get((line_index, 0)),
                targets.get((line_index, -1)),
            )
            for line_index, line in enumerate(lines)
        ]

        line_tree = STRtree(clustered)
        projected_targets: dict[tuple[int, int], Point] = {}
        for line_index, line in enumerate(clustered):
            for endpoint_index in (0, -1):
                point = Point(line.coords[endpoint_index])
                nearby = [
                    int(candidate)
                    for candidate in line_tree.query(point.buffer(tolerance))
                    if int(candidate) != line_index
                ]
                if not nearby or any(point.distance(clustered[item]) <= 1e-12 for item in nearby):
                    continue
                target_index = min(nearby, key=lambda item: (point.distance(clustered[item]), item))
                distance = point.distance(clustered[target_index])
                if distance <= tolerance:
                    projected_targets[(line_index, endpoint_index)] = nearest_points(
                        point, clustered[target_index]
                    )[1]

        result = [
            self._replace_endpoints(
                line,
                projected_targets.get((line_index, 0)),
                projected_targets.get((line_index, -1)),
            )
            for line_index, line in enumerate(clustered)
        ]
        moved = len(targets) + len(projected_targets)
        return result, moved

    @staticmethod
    def _replace_endpoints(line: LineString, start: Point | None, end: Point | None) -> LineString:
        coordinates = list(line.coords)

        def compatible(point: Point, original: tuple[float, ...]) -> tuple[float, ...]:
            target = tuple(point.coords[0])
            if len(original) == 3 and len(target) == 2:
                return (target[0], target[1], original[2])
            return target[: len(original)]

        if start is not None:
            coordinates[0] = compatible(start, coordinates[0])
        if end is not None:
            coordinates[-1] = compatible(end, coordinates[-1])
        candidate = LineString(coordinates)
        return candidate if candidate.length > 0 else line

    @staticmethod
    def _provenance(
        segments: Sequence[LineString],
        source_parts: Sequence[LineString],
        owners: Sequence[int],
        epsilon: float,
    ) -> list[tuple[int, ...]]:
        tree = STRtree(source_parts)
        result: list[tuple[int, ...]] = []
        for segment in segments:
            matched = {
                owners[int(candidate)]
                for candidate in tree.query(segment)
                if segment.difference(source_parts[int(candidate)]).length <= epsilon
            }
            if not matched:
                nearest = tree.nearest(segment)
                matched.add(owners[int(nearest)])
            result.append(tuple(sorted(matched)))
        return result


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
