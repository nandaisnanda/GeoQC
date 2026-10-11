"""Connect disconnected road components with a minimum spanning forest."""

from collections.abc import Sequence

import shapely
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from geoqc.domain.models.spatial_intelligence import (
    RoadComponentConnectionConfig,
    RoadComponentConnectionResult,
    RoadComponentConnector,
)
from geoqc.infrastructure.gis.spatial_helpers import _loads, _wkt


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> bool:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return False
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1
        return True


class ShapelyRoadNetworkConnector:
    """Build deterministic shortest connectors between road components."""

    def connect(
        self,
        geometries_wkt: Sequence[str],
        config: RoadComponentConnectionConfig,
    ) -> RoadComponentConnectionResult:
        geometries = _loads(geometries_wkt)
        if any(item.geom_type not in {"LineString", "MultiLineString"} for item in geometries):
            raise ValueError("road connector accepts only line geometries")
        if any(item.is_empty for item in geometries):
            raise ValueError("road connector does not accept empty geometries")

        lines = self._line_parts(geometries)
        if not lines:
            return RoadComponentConnectionResult(len(geometries), 0, 0, 0, ())
        component_ids = self._component_ids(lines, config.node_tolerance)
        component_count = len(set(component_ids))
        if component_count <= 1:
            return RoadComponentConnectionResult(
                len(geometries), len(lines), component_count, component_count, ()
            )

        component_lines: dict[int, list[LineString]] = {}
        for line, component in zip(lines, component_ids, strict=True):
            component_lines.setdefault(component, []).append(line)
        component_keys = sorted(component_lines)
        component_geometries = [
            shapely.union_all(component_lines[component]) for component in component_keys
        ]

        candidates: list[tuple[float, int, int, LineString]] = []
        for left, left_geometry in enumerate(component_geometries):
            for right in range(left + 1, len(component_geometries)):
                connector = shapely.shortest_line(left_geometry, component_geometries[right])
                if not isinstance(connector, LineString) or connector.is_empty:
                    continue
                distance = float(connector.length)
                if distance <= config.node_tolerance:
                    continue
                if (
                    config.max_connection_distance is not None
                    and distance > config.max_connection_distance
                ):
                    continue
                candidates.append((distance, left, right, connector))

        candidates.sort(key=lambda item: (item[0], item[1], item[2], _wkt(item[3])))
        forest = _UnionFind(component_count)
        connectors: list[RoadComponentConnector] = []
        for distance, left, right, geometry in candidates:
            if not forest.union(left, right):
                continue
            connectors.append(
                RoadComponentConnector(
                    connector_index=len(connectors),
                    source_component=component_keys[left],
                    target_component=component_keys[right],
                    geometry_wkt=_wkt(geometry),
                    length=distance,
                )
            )
            if len(connectors) == component_count - 1:
                break

        remaining = len({forest.find(index) for index in range(component_count)})
        return RoadComponentConnectionResult(
            input_feature_count=len(geometries),
            input_part_count=len(lines),
            initial_component_count=component_count,
            remaining_component_count=remaining,
            connectors=tuple(connectors),
        )

    @staticmethod
    def _line_parts(geometries: Sequence[BaseGeometry]) -> list[LineString]:
        parts: list[LineString] = []
        for geometry in geometries:
            if isinstance(geometry, LineString):
                source_parts = [geometry]
            else:
                assert isinstance(geometry, MultiLineString)
                source_parts = list(geometry.geoms)
            for part in source_parts:
                cleaned = shapely.force_2d(shapely.remove_repeated_points(part, 0.0))
                if isinstance(cleaned, LineString) and cleaned.length > 0:
                    parts.append(cleaned)
        return parts

    @staticmethod
    def _component_ids(lines: Sequence[LineString], tolerance: float) -> list[int]:
        endpoints = [
            Point(coordinate) for line in lines for coordinate in (line.coords[0], line.coords[-1])
        ]
        endpoint_tree = STRtree(endpoints)
        graph = _UnionFind(len(lines))
        for endpoint_index, point in enumerate(endpoints):
            line_index = endpoint_index // 2
            query_geometry = point if tolerance == 0 else point.buffer(tolerance)
            for candidate in endpoint_tree.query(query_geometry):
                other_endpoint = int(candidate)
                other_line = other_endpoint // 2
                connected = point.distance(endpoints[other_endpoint]) <= tolerance
                if other_line != line_index and connected:
                    graph.union(line_index, other_line)
        roots = [graph.find(index) for index in range(len(lines))]
        ordered_roots = {root: index for index, root in enumerate(dict.fromkeys(roots))}
        return [ordered_roots[root] for root in roots]
