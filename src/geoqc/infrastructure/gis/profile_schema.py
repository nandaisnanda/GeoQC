"""Profile schema for the canonical dataset workflow."""

from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Any

from geoqc.domain.models import (
    AttributeOverlapPolicy,
    AttributeRule,
    AttributeRuleType,
    QualityProfile,
    TopologyRule,
    TopologyRuleType,
)
from geoqc.domain.rules import Severity


def _topology_rule(raw: Mapping[str, object]) -> TopologyRule:
    _reject_unknown(
        raw,
        {
            "type",
            "layer",
            "reference_layer",
            "tolerance",
            "minimum_area",
            "minimum_length",
            "minimum_distance",
            "minimum_angle",
            "allowed_geometry_types",
            "precision_grid_size",
            "attribute_column",
            "overlap_policy",
            "severity",
        },
        "topology rule",
    )
    return TopologyRule(
        rule_type=TopologyRuleType(str(raw.get("type", ""))),
        layer=str(raw.get("layer", "")),
        reference_layer=str(raw["reference_layer"]) if raw.get("reference_layer") else None,
        tolerance=_number(raw.get("tolerance", 0.0), "topology rule tolerance"),
        minimum_area=_number(raw.get("minimum_area", 0.0), "topology rule minimum_area"),
        minimum_length=_number(raw.get("minimum_length", 0.0), "topology rule minimum_length"),
        minimum_distance=_number(
            raw.get("minimum_distance", 0.0), "topology rule minimum_distance"
        ),
        minimum_angle=_number(raw.get("minimum_angle", 0.0), "topology rule minimum_angle"),
        allowed_geometry_types=tuple(
            str(item)
            for item in _sequence(raw.get("allowed_geometry_types", ()), "allowed_geometry_types")
        ),
        precision_grid_size=_number(
            raw.get("precision_grid_size", 0.0), "topology rule precision_grid_size"
        ),
        attribute_column=(
            str(raw["attribute_column"]) if raw.get("attribute_column") is not None else None
        ),
        overlap_policy=AttributeOverlapPolicy(str(raw.get("overlap_policy", "deny_all"))),
        severity=Severity(str(raw.get("severity", "error"))),
    )


def _attribute_rule(raw: Mapping[str, object]) -> AttributeRule:
    _reject_unknown(
        raw,
        {"column", "type", "severity", "allowed_values", "minimum", "maximum"},
        "attribute schema rule",
    )
    return AttributeRule(
        column=str(raw.get("column", "")),
        rule_type=AttributeRuleType(str(raw.get("type", ""))),
        severity=Severity(str(raw.get("severity", "error"))),
        allowed_values=tuple(_sequence(raw.get("allowed_values", ()), "allowed_values")),
        minimum=_number(raw["minimum"], "attribute minimum")
        if raw.get("minimum") is not None
        else None,
        maximum=_number(raw["maximum"], "attribute maximum")
        if raw.get("maximum") is not None
        else None,
    )


def _profile_dict(profile: QualityProfile) -> dict[str, object]:
    return {
        "name": profile.name,
        "version": profile.version,
        "id_column": profile.id_column,
        "enabled_checks": list(profile.enabled_checks),
        "expected_geometry_types": list(profile.expected_geometry_types),
        "preset": profile.preset.value if profile.preset else None,
        "tolerance": profile.tolerance,
        "minimum_area": profile.minimum_area,
        "crs": {
            "required": profile.require_crs,
            "require_projected": profile.require_projected_crs,
            "allowed": list(profile.allowed_crs),
        },
        "topology_rules": [
            {
                "type": item.rule_type.value,
                "layer": item.layer,
                "reference_layer": item.reference_layer,
                "tolerance": item.tolerance,
                "minimum_area": item.minimum_area,
                "minimum_length": item.minimum_length,
                "minimum_distance": item.minimum_distance,
                "minimum_angle": item.minimum_angle,
                "allowed_geometry_types": list(item.allowed_geometry_types),
                "precision_grid_size": item.precision_grid_size,
                "attribute_column": item.attribute_column,
                "overlap_policy": item.overlap_policy.value,
                "severity": item.severity.value,
            }
            for item in profile.topology_rules
        ],
        "attribute_schema": [
            {
                "type": item.rule_type.value,
                "column": item.column,
                "severity": item.severity.value,
                "allowed_values": list(item.allowed_values),
                "minimum": item.minimum,
                "maximum": item.maximum,
            }
            for item in profile.attribute_rules
        ],
        "scoring": {
            "category_weights": dict(profile.scoring.category_weights),
            "severity_penalties": {
                key.value: value for key, value in profile.scoring.severity_penalties.items()
            },
            "category_caps": dict(profile.scoring.category_caps),
            "repeated_feature_cap": profile.scoring.repeated_feature_cap,
        },
        "severity_overrides": {
            key: value.value for key, value in profile.severity_overrides.items()
        },
        "quality_gate": {
            "minimum_score": profile.gate.minimum_score,
            "fail_on": profile.gate.fail_on.value,
            "allow_unknown_crs": profile.gate.allow_unknown_crs,
        },
    }


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object, name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be an array")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{name} must be numeric")
    try:
        number = float(value)
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error
    if not isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _reject_unknown(value: Mapping[str, object], allowed: set[str], name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{name} contains unknown fields: {unknown}")


def _integer(value: object, name: str) -> int:
    number = _number(value, name)
    if not number.is_integer():
        raise ValueError(f"{name} must be an integer")
    return int(number)
