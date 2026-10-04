"""Declarative same-layer and cross-layer topology evaluation."""

from collections.abc import Mapping, Sequence

import shapely

from geoqc.domain.models import DatasetIssue, DatasetLayer, TopologyRule, TopologyRuleType
from geoqc.infrastructure.gis.finding_builders import (
    _cross_layer_issues,
    _duplicate_issues,
    _gap_issues,
    _issue_sort_key,
    _minimum_area_issues,
    _overlap_issues,
)
from geoqc.infrastructure.gis.topology_rules_v2 import evaluate_advanced_rule


def evaluate_topology_rules(
    layers: Sequence[DatasetLayer], rules: Sequence[TopologyRule]
) -> tuple[DatasetIssue, ...]:
    """Evaluate declarative same-layer and cross-layer topology constraints."""
    loaded = {
        layer.name: tuple(shapely.from_wkt(value) for value in layer.geometries_wkt)
        for layer in layers
    }
    attributes = {layer.name: layer.attributes for layer in layers}
    if len(loaded) != len(layers):
        raise ValueError("layer names must be unique")
    findings: list[DatasetIssue] = []
    for rule in rules:
        if rule.layer not in loaded:
            raise ValueError(f"unknown layer: {rule.layer}")
        source = loaded[rule.layer]
        if rule.rule_type is TopologyRuleType.NO_OVERLAP:
            findings.extend(_overlap_issues(source, rule.layer, rule.tolerance, rule.severity))
        elif rule.rule_type is TopologyRuleType.NO_GAP:
            findings.extend(_gap_issues(source, rule.layer, rule.tolerance, rule.severity))
        elif rule.rule_type is TopologyRuleType.NO_DUPLICATE:
            findings.extend(_duplicate_issues(source, rule.layer, rule.tolerance, rule.severity))
        elif rule.rule_type is TopologyRuleType.MINIMUM_AREA:
            findings.extend(
                _minimum_area_issues(source, rule.layer, rule.minimum_area, rule.severity)
            )
        elif rule.rule_type in {
            TopologyRuleType.MUST_BE_INSIDE,
            TopologyRuleType.MUST_NOT_INTERSECT,
        }:
            assert rule.reference_layer is not None
            if rule.reference_layer not in loaded:
                raise ValueError(f"unknown reference layer: {rule.reference_layer}")
            findings.extend(_cross_layer_issues(source, loaded[rule.reference_layer], rule))
        else:
            reference = None
            reference_attributes: Sequence[Mapping[str, str | int | float | bool | None]] = ()
            if rule.reference_layer is not None:
                if rule.reference_layer not in loaded:
                    raise ValueError(f"unknown reference layer: {rule.reference_layer}")
                reference = loaded[rule.reference_layer]
                reference_attributes = attributes[rule.reference_layer]
            findings.extend(
                evaluate_advanced_rule(
                    source,
                    attributes[rule.layer],
                    reference,
                    reference_attributes,
                    rule,
                )
            )
    return tuple(sorted(findings, key=_issue_sort_key))
