"""Deprecated P0 argument adapters for the canonical dataset audit workflow."""

from collections.abc import Iterable

from geoqc.domain.models import (
    AttributeRule,
    AttributeRuleType,
    AttributeSchema,
    QualityProfile,
)

_CHECK_NAMES = ("geometry", "crs", "attributes", "topology", "spatial")


def profile_from_legacy_arguments(
    base: QualityProfile,
    *,
    schema: AttributeSchema | None,
    checks: str | Iterable[str],
) -> QualityProfile:
    """Translate deprecated P0 options into one canonical quality profile."""
    enabled = _normalize_checks(checks)
    rules = list(base.attribute_rules)
    if schema is not None:
        rules.extend(
            AttributeRule(column.name, AttributeRuleType.REQUIRED) for column in schema.columns
        )
        rules.extend(
            AttributeRule(column.name, AttributeRuleType.NOT_NULL)
            for column in schema.columns
            if not column.nullable
        )
        rules.append(AttributeRule(schema.id_column, AttributeRuleType.UNIQUE))
    return QualityProfile(
        name=base.name,
        version=base.version,
        preset=base.preset,
        tolerance=base.tolerance,
        minimum_area=base.minimum_area,
        require_crs=base.require_crs,
        require_projected_crs=base.require_projected_crs,
        allowed_crs=base.allowed_crs,
        id_column=base.id_column,
        enabled_checks=enabled,
        expected_geometry_types=base.expected_geometry_types,
        topology_rules=base.topology_rules,
        attribute_rules=tuple(rules),
        severity_overrides=base.severity_overrides,
        scoring=base.scoring,
        gate=base.gate,
    )


def _normalize_checks(checks: str | Iterable[str]) -> tuple[str, ...]:
    values = _CHECK_NAMES if isinstance(checks, str) and checks.casefold() == "all" else checks
    if isinstance(values, str):
        values = (values,)
    normalized = tuple(dict.fromkeys(str(value).strip().casefold() for value in values))
    unknown = set(normalized).difference(_CHECK_NAMES)
    if not normalized or unknown:
        detail = ", ".join(sorted(unknown)) if unknown else "no checks"
        raise ValueError(f"unknown audit checks: {detail}")
    return normalized
