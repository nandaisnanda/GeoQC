"""Advanced declarative topology checks used by the dataset workflow."""

from collections.abc import Mapping, Sequence
from math import acos, degrees, hypot

import shapely
from shapely.geometry import LineString, MultiPoint, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from geoqc.domain.models.quality_workflow import (
    AttributeOverlapPolicy,
    DatasetIssue,
    IssueGeometryKind,
    RepairRisk,
    TopologyRule,
    TopologyRuleType,
)

AttributeValue = str | int | float | bool | None


def evaluate_advanced_rule(
    source: Sequence[BaseGeometry],
    source_attributes: Sequence[Mapping[str, AttributeValue]],
    reference: Sequence[BaseGeometry] | None,
    reference_attributes: Sequence[Mapping[str, AttributeValue]],
    rule: TopologyRule,
) -> list[DatasetIssue]:
    """Dispatch one Phase-2 rule and return deterministic issue records."""
    if rule.rule_type is TopologyRuleType.BOUNDARY_MUST_MATCH:
        assert reference is not None
        return _boundary_mismatch(source, reference, rule)
    if rule.rule_type in {TopologyRuleType.NO_DANGLES, TopologyRuleType.ENDPOINT_MUST_CONNECT}:
        return _endpoint_issues(source, rule)
    if rule.rule_type is TopologyRuleType.NO_OVERSHOOT_UNDERSHOOT:
        return _overshoot_undershoot(source, rule)
    if rule.rule_type is TopologyRuleType.ALLOWED_GEOMETRY_TYPE:
        return _geometry_type_issues(source, rule)
    if rule.rule_type is TopologyRuleType.SINGLEPART_ONLY:
        return _multipart_issues(source, rule)
    if rule.rule_type is TopologyRuleType.NO_SPIKES:
        return _spike_issues(source, rule)
    if rule.rule_type is TopologyRuleType.MINIMUM_SEGMENT_LENGTH:
        return _minimum_segment_issues(source, rule)
    if rule.rule_type is TopologyRuleType.MINIMUM_VERTEX_DISTANCE:
        return _minimum_vertex_issues(source, rule)
    if rule.rule_type in {
        TopologyRuleType.MUST_TOUCH,
        TopologyRuleType.MUST_INTERSECT,
        TopologyRuleType.MUST_COVER,
    }:
        assert reference is not None
        return _relation_issues(source, reference, rule)
    if rule.rule_type is TopologyRuleType.ATTRIBUTE_OVERLAP:
        return _attribute_overlap_issues(
            source, source_attributes, reference, reference_attributes, rule
        )
    if rule.rule_type is TopologyRuleType.PRECISION_GRID:
        return _precision_grid_issues(source, rule)
    raise ValueError(f"unsupported advanced topology rule: {rule.rule_type.value}")


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


def _relation_issues(
    source: Sequence[BaseGeometry], reference: Sequence[BaseGeometry], rule: TopologyRule
) -> list[DatasetIssue]:
    tree = STRtree(reference) if reference else None
    findings: list[DatasetIssue] = []
    for index, geometry in enumerate(source):
        candidates = [] if tree is None else [int(item) for item in tree.query(geometry)]
        if rule.rule_type is TopologyRuleType.MUST_TOUCH:
            valid = any(geometry.touches(reference[item]) for item in candidates)
        elif rule.rule_type is TopologyRuleType.MUST_INTERSECT:
            valid = any(geometry.intersects(reference[item]) for item in candidates)
        else:
            valid = any(
                geometry.buffer(rule.tolerance).covers(reference[item]) for item in candidates
            )
        if not valid:
            findings.append(
                _issue(
                    rule,
                    index,
                    geometry,
                    f"Feature fails {rule.rule_type.value}",
                    (
                        f"Feature {index} does not satisfy {rule.rule_type.value} "
                        f"with {rule.reference_layer}."
                    ),
                    f"Edit the feature so it satisfies {rule.rule_type.value}.",
                )
            )
    return findings


def _attribute_overlap_issues(
    source: Sequence[BaseGeometry],
    source_attributes: Sequence[Mapping[str, AttributeValue]],
    reference: Sequence[BaseGeometry] | None,
    reference_attributes: Sequence[Mapping[str, AttributeValue]],
    rule: TopologyRule,
) -> list[DatasetIssue]:
    target = source if reference is None else reference
    target_attributes = source_attributes if reference is None else reference_attributes
    tree = STRtree(target) if target else None
    findings: list[DatasetIssue] = []
    column = rule.attribute_column or ""
    if not source_attributes or any(column not in item for item in source_attributes):
        raise ValueError(f"attribute {column!r} is missing from layer {rule.layer}")
    if reference is not None and (
        not reference_attributes or any(column not in item for item in reference_attributes)
    ):
        raise ValueError(f"attribute {column!r} is missing from layer {rule.reference_layer}")
    for left, geometry in enumerate(source):
        if tree is None:
            continue
        for raw in tree.query(geometry):
            right = int(raw)
            if reference is None and right <= left:
                continue
            overlap = geometry.intersection(target[right])
            if overlap.is_empty or overlap.area <= rule.tolerance:
                continue
            left_value = source_attributes[left].get(column) if source_attributes else None
            right_value = target_attributes[right].get(column) if target_attributes else None
            equal = left_value == right_value
            allowed = (rule.overlap_policy is AttributeOverlapPolicy.ALLOW_EQUAL and equal) or (
                rule.overlap_policy is AttributeOverlapPolicy.ALLOW_DIFFERENT and not equal
            )
            if allowed:
                continue
            findings.append(
                _issue(
                    rule,
                    left,
                    overlap,
                    "Attribute-controlled overlap",
                    f"Features {left} and {right} overlap contrary to {rule.overlap_policy.value}.",
                    "Review the overlap and its controlling attribute values.",
                    related=right,
                    metadata={
                        "attribute": column,
                        "source_value": _metadata_value(left_value),
                        "related_value": _metadata_value(right_value),
                        "overlap_area": float(overlap.area),
                    },
                )
            )
    return findings


def _precision_grid_issues(
    source: Sequence[BaseGeometry], rule: TopologyRule
) -> list[DatasetIssue]:
    findings: list[DatasetIssue] = []
    size = rule.precision_grid_size
    for index, geometry in enumerate(source):
        offenders: list[tuple[float, float]] = []
        maximum = 0.0
        for coordinate in shapely.get_coordinates(geometry):
            x, y = float(coordinate[0]), float(coordinate[1])
            snapped = (round(x / size) * size, round(y / size) * size)
            deviation = hypot(x - snapped[0], y - snapped[1])
            if deviation > rule.tolerance + 1e-12:
                offenders.append((x, y))
                maximum = max(maximum, deviation)
        if not offenders:
            continue
        unique = list(dict.fromkeys(offenders))
        location: BaseGeometry = Point(unique[0]) if len(unique) == 1 else MultiPoint(unique)
        findings.append(
            _issue(
                rule,
                index,
                location,
                "Coordinate is off the precision grid",
                f"Feature {index} has {len(unique)} vertex/vertices off the {size:.6g} grid.",
                "Snap coordinates to the configured precision grid and revalidate topology.",
                metadata={
                    "grid_size": size,
                    "off_grid_vertices": len(unique),
                    "maximum_deviation": maximum,
                },
            )
        )
    return findings


def _line_records(source: Sequence[BaseGeometry]) -> list[tuple[int, LineString]]:
    records: list[tuple[int, LineString]] = []
    for owner, geometry in enumerate(source):
        if isinstance(geometry, LineString):
            records.append((owner, geometry))
        elif geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
            records.extend(
                (owner, part)
                for part in shapely.get_parts(geometry)
                if isinstance(part, LineString) and not part.is_empty
            )
    return records


def _coordinate_sequences(
    source: Sequence[BaseGeometry],
) -> list[tuple[int, list[tuple[float, float]], bool]]:
    output: list[tuple[int, list[tuple[float, float]], bool]] = []
    pending = list(enumerate(source))
    while pending:
        owner, geometry = pending.pop(0)
        if isinstance(geometry, LineString):
            coordinates = [(float(x), float(y)) for x, y, *_ in geometry.coords]
            output.append((owner, coordinates, geometry.is_closed))
        elif isinstance(geometry, Polygon):
            exterior = [(float(x), float(y)) for x, y, *_ in geometry.exterior.coords]
            output.append((owner, exterior, True))
            output.extend(
                (owner, [(float(x), float(y)) for x, y, *_ in ring.coords], True)
                for ring in geometry.interiors
            )
        elif geometry.geom_type.startswith("Multi") or geometry.geom_type == "GeometryCollection":
            pending[0:0] = [(owner, part) for part in shapely.get_parts(geometry)]
    return output


def _points(geometry: BaseGeometry) -> list[Point]:
    if isinstance(geometry, Point):
        return [geometry]
    if geometry.geom_type in {"MultiPoint", "GeometryCollection"}:
        return [item for item in shapely.get_parts(geometry) if isinstance(item, Point)]
    return []


def _angle(
    before: tuple[float, float], vertex: tuple[float, float], after: tuple[float, float]
) -> float | None:
    first = (before[0] - vertex[0], before[1] - vertex[1])
    second = (after[0] - vertex[0], after[1] - vertex[1])
    norm = hypot(*first) * hypot(*second)
    if norm == 0:
        return None
    cosine = max(-1.0, min(1.0, (first[0] * second[0] + first[1] * second[1]) / norm))
    return degrees(acos(cosine))


def _issue(
    rule: TopologyRule,
    feature_index: int,
    geometry: BaseGeometry,
    title: str,
    message: str,
    recommendation: str,
    *,
    related: int | None = None,
    metadata: Mapping[str, str | int | float | bool | None] | None = None,
) -> DatasetIssue:
    return DatasetIssue(
        code=f"TOP-{rule.rule_type.value.upper().replace('_', '-')}",
        issue_type=rule.rule_type.value,
        title=title,
        message=message,
        severity=rule.severity,
        category="topology",
        recommendation=recommendation,
        repair_risk=RepairRisk.REVIEW,
        geometry_kind=_kind(geometry),
        geometry_wkt=str(shapely.to_wkt(geometry, rounding_precision=-1)),
        layer=rule.layer,
        feature_index=feature_index,
        related_feature_index=related,
        metadata=metadata or {},
    )


def _kind(geometry: BaseGeometry) -> IssueGeometryKind:
    dimension = int(shapely.get_dimensions(geometry))
    if dimension >= 2:
        return IssueGeometryKind.POLYGON
    if dimension == 1:
        return IssueGeometryKind.LINE
    return IssueGeometryKind.POINT


def _unique(findings: Sequence[DatasetIssue]) -> list[DatasetIssue]:
    return list({item.fingerprint: item for item in findings}.values())


def _metadata_value(value: AttributeValue) -> str | int | float | bool | None:
    return value
