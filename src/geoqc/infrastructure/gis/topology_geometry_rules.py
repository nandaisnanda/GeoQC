"""Per-feature geometry-shape topology rules."""

from collections.abc import Sequence
from math import hypot

import shapely
from shapely.geometry import LineString, MultiPoint, Point
from shapely.geometry.base import BaseGeometry

from geoqc.domain.models.quality_workflow import (
    DatasetIssue,
    TopologyRule,
)
from geoqc.infrastructure.gis.topology_rule_helpers import (
    _angle,
    _coordinate_sequences,
    _issue,
    _unique,
)

AttributeValue = str | int | float | bool | None


def _geometry_type_issues(source: Sequence[BaseGeometry], rule: TopologyRule) -> list[DatasetIssue]:
    allowed = {item.casefold() for item in rule.allowed_geometry_types}
    return [
        _issue(
            rule,
            index,
            geometry,
            "Disallowed geometry type",
            (
                f"Feature {index} is {geometry.geom_type}; allowed types: "
                f"{', '.join(rule.allowed_geometry_types)}."
            ),
            "Convert the feature to an allowed geometry type.",
            metadata={"geometry_type": geometry.geom_type},
        )
        for index, geometry in enumerate(source)
        if geometry.geom_type.casefold() not in allowed
    ]


def _multipart_issues(source: Sequence[BaseGeometry], rule: TopologyRule) -> list[DatasetIssue]:
    findings: list[DatasetIssue] = []
    for index, geometry in enumerate(source):
        if not (
            geometry.geom_type.startswith("Multi") or geometry.geom_type == "GeometryCollection"
        ):
            continue
        part_count = int(shapely.get_num_geometries(geometry))
        findings.append(
            _issue(
                rule,
                index,
                geometry,
                "Multipart geometry is not allowed",
                f"Feature {index} contains {part_count} parts.",
                "Explode the multipart feature into singlepart features.",
                metadata={"part_count": part_count},
            )
        )
    return findings


def _spike_issues(source: Sequence[BaseGeometry], rule: TopologyRule) -> list[DatasetIssue]:
    findings: list[DatasetIssue] = []
    for owner, coordinates, closed in _coordinate_sequences(source):
        points = coordinates[:-1] if closed and coordinates[0] == coordinates[-1] else coordinates
        count = len(points)
        positions = range(count) if closed else range(1, count - 1)
        for position in positions:
            before = points[(position - 1) % count]
            vertex = points[position]
            after = points[(position + 1) % count]
            angle = _angle(before, vertex, after)
            if angle is None or angle >= rule.minimum_angle:
                continue
            findings.append(
                _issue(
                    rule,
                    owner,
                    Point(vertex),
                    "Spike or acute angle",
                    f"Feature {owner} has a {angle:.6g} degree angle.",
                    "Review and remove the spike or reshape the acute corner.",
                    metadata={"angle_degrees": angle},
                )
            )
    return _unique(findings)


def _minimum_segment_issues(
    source: Sequence[BaseGeometry], rule: TopologyRule
) -> list[DatasetIssue]:
    findings: list[DatasetIssue] = []
    for owner, coordinates, _ in _coordinate_sequences(source):
        for start, end in zip(coordinates, coordinates[1:], strict=False):
            length = hypot(end[0] - start[0], end[1] - start[1])
            if length >= rule.minimum_length:
                continue
            findings.append(
                _issue(
                    rule,
                    owner,
                    LineString([start, end]) if length else Point(start),
                    "Segment below minimum length",
                    f"Feature {owner} has a {length:.6g} unit segment.",
                    "Remove or reshape the short segment.",
                    metadata={"segment_length": length},
                )
            )
    return _unique(findings)


def _minimum_vertex_issues(
    source: Sequence[BaseGeometry], rule: TopologyRule
) -> list[DatasetIssue]:
    findings: list[DatasetIssue] = []
    for owner, coordinates, closed in _coordinate_sequences(source):
        points = coordinates[:-1] if closed and coordinates[0] == coordinates[-1] else coordinates
        for left, first in enumerate(points):
            for right in range(left + 1, len(points)):
                if right == left + 1 or (closed and left == 0 and right == len(points) - 1):
                    continue
                second = points[right]
                distance = hypot(second[0] - first[0], second[1] - first[1])
                if distance >= rule.minimum_distance:
                    continue
                findings.append(
                    _issue(
                        rule,
                        owner,
                        MultiPoint([first, second]),
                        "Vertices below minimum distance",
                        f"Feature {owner} has non-adjacent vertices {distance:.6g} units apart.",
                        "Merge or move vertices that are closer than the configured minimum.",
                        metadata={"vertex_distance": distance},
                    )
                )
    return _unique(findings)
