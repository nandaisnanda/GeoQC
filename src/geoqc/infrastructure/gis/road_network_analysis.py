"""Shapely road-network analysis adapter."""

from collections.abc import Sequence

import shapely
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from geoqc.domain.models.spatial_intelligence import (
    RoadFinding,
    RoadIssueType,
    RoadNetworkConfig,
    RoadNetworkReport,
)
from geoqc.infrastructure.gis.spatial_helpers import _loads, _wkt


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
