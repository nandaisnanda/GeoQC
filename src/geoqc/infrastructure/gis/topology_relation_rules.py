"""Cross-feature, attribute, relation, and precision topology rules."""

from collections.abc import Mapping, Sequence
from math import hypot

import shapely
from shapely.geometry import MultiPoint, Point
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from geoqc.domain.models.quality_workflow import (
    AttributeOverlapPolicy,
    DatasetIssue,
    TopologyRule,
    TopologyRuleType,
)
from geoqc.infrastructure.gis.topology_rule_helpers import _issue, _metadata_value

AttributeValue = str | int | float | bool | None


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
