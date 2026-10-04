"""Shapely road-network repair adapter."""

from collections.abc import Sequence

import shapely
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import nearest_points
from shapely.strtree import STRtree

from geoqc.domain.models.spatial_intelligence import (
    RoadNetworkRepairConfig,
    RoadNetworkRepairResult,
    RoadRepairSegment,
)
from geoqc.infrastructure.gis.spatial_helpers import _loads, _wkt


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
