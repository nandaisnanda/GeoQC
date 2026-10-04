"""Network and boundary topology rules."""

from collections.abc import Sequence

import shapely
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from geoqc.domain.models.quality_workflow import (
    DatasetIssue,
    TopologyRule,
    TopologyRuleType,
)
from geoqc.infrastructure.gis.topology_rule_helpers import _issue, _line_records, _points, _unique

AttributeValue = str | int | float | bool | None


def _boundary_mismatch(
    source: Sequence[BaseGeometry], reference: Sequence[BaseGeometry], rule: TopologyRule
) -> list[DatasetIssue]:
    target = shapely.union_all([item.boundary for item in reference if not item.is_empty])
    findings: list[DatasetIssue] = []
    for index, geometry in enumerate(source):
        boundary = geometry.boundary
        matched = target.buffer(rule.tolerance) if rule.tolerance else target
        mismatch = boundary.difference(matched)
        if mismatch.is_empty:
            continue
        findings.append(
            _issue(
                rule,
                index,
                mismatch,
                "Boundary mismatch",
                f"Feature {index} has {mismatch.length:.6g} unmatched boundary units.",
                f"Snap or reshape the boundary to match {rule.reference_layer}.",
                metadata={"unmatched_length": float(mismatch.length)},
            )
        )
    return findings


def _endpoint_issues(source: Sequence[BaseGeometry], rule: TopologyRule) -> list[DatasetIssue]:
    records = _line_records(source)
    lines = [line for _, line in records]
    tolerance = rule.tolerance
    findings: list[DatasetIssue] = []
    for line_index, (owner, line) in enumerate(records):
        if line.is_closed:
            continue
        for endpoint in (Point(line.coords[0]), Point(line.coords[-1])):
            others = [other for index, other in enumerate(lines) if index != line_index]
            if rule.rule_type is TopologyRuleType.NO_DANGLES:
                connected = any(
                    endpoint.distance(Point(other.coords[position])) <= tolerance
                    for other in others
                    for position in (0, -1)
                )
                title = "Dangling endpoint"
            else:
                connected = any(endpoint.distance(other) <= tolerance for other in others)
                title = "Endpoint is not connected"
            if connected:
                continue
            findings.append(
                _issue(
                    rule,
                    owner,
                    endpoint,
                    title,
                    f"Feature {owner} has an unconnected endpoint.",
                    "Connect the endpoint to the intended network feature.",
                )
            )
    return _unique(findings)


def _overshoot_undershoot(source: Sequence[BaseGeometry], rule: TopologyRule) -> list[DatasetIssue]:
    records = _line_records(source)
    findings: list[DatasetIssue] = []
    tolerance = rule.tolerance
    if tolerance <= 0:
        return findings
    for left, (owner, line) in enumerate(records):
        if line.is_closed:
            continue
        endpoints = (
            (Point(line.coords[0]), 0.0),
            (Point(line.coords[-1]), line.length),
        )
        for endpoint, measure in endpoints:
            nearest: tuple[int, float] | None = None
            for right, (other_owner, other) in enumerate(records):
                if right == left:
                    continue
                distance = endpoint.distance(other)
                if (
                    0 < distance <= tolerance
                    and not line.intersects(other)
                    and (nearest is None or distance < nearest[1])
                ):
                    nearest = (other_owner, distance)
                intersection = line.intersection(other)
                for point in _points(intersection):
                    tail = abs(line.project(point) - measure)
                    if 1e-12 < tail <= tolerance and endpoint.distance(other) > 1e-12:
                        findings.append(
                            _issue(
                                rule,
                                owner,
                                endpoint,
                                "Line overshoot",
                                f"Feature {owner} extends {tail:.6g} units beyond an intersection.",
                                "Trim the endpoint back to the intersection.",
                                related=other_owner,
                                metadata={"subtype": "overshoot", "distance": float(tail)},
                            )
                        )
            if nearest is not None:
                findings.append(
                    _issue(
                        rule,
                        owner,
                        endpoint,
                        "Line undershoot",
                        f"Feature {owner} stops {nearest[1]:.6g} units before a nearby line.",
                        "Extend or snap the endpoint to the nearby line.",
                        related=nearest[0],
                        metadata={"subtype": "undershoot", "distance": float(nearest[1])},
                    )
                )
    return _unique(findings)
