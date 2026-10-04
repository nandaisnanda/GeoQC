"""Dispatcher for advanced declarative topology checks."""

from collections.abc import Mapping, Sequence

from shapely.geometry.base import BaseGeometry

from geoqc.domain.models.quality_workflow import DatasetIssue, TopologyRule, TopologyRuleType
from geoqc.infrastructure.gis.topology_geometry_rules import (
    _geometry_type_issues,
    _minimum_segment_issues,
    _minimum_vertex_issues,
    _multipart_issues,
    _spike_issues,
)
from geoqc.infrastructure.gis.topology_network_rules import (
    _boundary_mismatch,
    _endpoint_issues,
    _overshoot_undershoot,
)
from geoqc.infrastructure.gis.topology_relation_rules import (
    _attribute_overlap_issues,
    _precision_grid_issues,
    _relation_issues,
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


__all__ = ["evaluate_advanced_rule"]
