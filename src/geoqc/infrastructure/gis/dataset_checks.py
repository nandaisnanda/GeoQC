"""Dataset checks for the canonical dataset workflow."""

from collections.abc import Sequence
from dataclasses import replace

import geopandas as gpd  # type: ignore[import-untyped]
import pandas as pd
from pyproj import CRS
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from geoqc.domain.models import (
    AttributeRule,
    AttributeRuleType,
    AuditCheckResult,
    CheckStatus,
    DatasetAuditResult,
    DatasetIssue,
    QualityProfile,
    RepairRisk,
)
from geoqc.domain.rules import Severity
from geoqc.infrastructure.gis.dataset_values import _kind, _wkt


def _checks_for_result(
    result: DatasetAuditResult, profile: QualityProfile | None
) -> tuple[AuditCheckResult, ...]:
    groups = {
        "geometry": tuple(issue for issue in result.issues if issue.category == "geometry"),
        "crs": tuple(issue for issue in result.issues if issue.category == "metadata"),
        "attributes": tuple(issue for issue in result.issues if issue.category == "attribute"),
        "topology": tuple(
            issue for issue in result.issues if issue.category in {"topology", "network"}
        ),
        "spatial": tuple(issue for issue in result.issues if issue.category == "spatial"),
    }
    checks_out: list[AuditCheckResult] = []
    for name, issues in groups.items():
        if profile is not None and name not in profile.enabled_checks:
            checks_out.append(
                AuditCheckResult(
                    name, CheckStatus.SKIPPED, reason="Check not selected by quality profile."
                )
            )
        elif name == "attributes" and (profile is None or not profile.attribute_rules):
            checks_out.append(
                AuditCheckResult(
                    name, CheckStatus.SKIPPED, reason="No attribute schema configured."
                )
            )
        elif (
            name == "topology"
            and profile is not None
            and _profile_needs_metric_crs(profile)
            and (result.crs_guard.crs is None or result.crs_guard.uses_angular_units)
        ):
            checks_out.append(
                AuditCheckResult(
                    name,
                    CheckStatus.SKIPPED,
                    reason=(
                        "Metric topology thresholds require a projected CRS. Define or "
                        "transform the dataset CRS, then run the audit again."
                    ),
                )
            )
        elif (
            not issues
            and name in {"topology", "spatial"}
            and (
                profile is None
                or (name == "topology" and not profile.topology_rules and profile.preset is None)
                or name == "spatial"
            )
        ):
            reason = (
                "Dataset CRS is missing. Define a projected CRS and configure the required "
                f"{name} rules before running this check."
                if result.crs_guard.crs is None
                else f"No {name} rules were configured."
            )
            checks_out.append(AuditCheckResult(name, CheckStatus.SKIPPED, reason=reason))
        else:
            checks_out.append(
                AuditCheckResult(
                    name,
                    CheckStatus.FAILED if issues else CheckStatus.PASSED,
                    issues,
                )
            )
    return tuple(checks_out)


def _check_name(category: str) -> str:
    return {
        "attribute": "attributes",
        "metadata": "crs",
        "network": "topology",
    }.get(category, category)


def _profile_needs_metric_crs(profile: QualityProfile) -> bool:
    if profile.tolerance > 0 or profile.minimum_area > 0:
        return True
    return any(
        value > 0
        for rule in profile.topology_rules
        for value in (
            rule.tolerance,
            rule.minimum_area,
            rule.minimum_length,
            rule.minimum_distance,
            rule.precision_grid_size,
        )
    )


def _metric_skip_reason(frame: gpd.GeoDataFrame, profile: QualityProfile) -> str | None:
    if not _profile_needs_metric_crs(profile):
        return None
    if frame.crs is None:
        return "Metric thresholds require a defined projected CRS."
    if CRS.from_user_input(frame.crs).is_geographic:
        return "Metric thresholds require a projected CRS, not angular units."
    return None


def _geometry_type_issues(
    frame: gpd.GeoDataFrame, layer: str, profile: QualityProfile
) -> list[DatasetIssue]:
    if not profile.expected_geometry_types:
        return []
    allowed = {item.casefold() for item in profile.expected_geometry_types}
    issues: list[DatasetIssue] = []
    for index, geometry in enumerate(frame.geometry):
        if geometry.geom_type.casefold() not in allowed:
            issues.append(
                DatasetIssue(
                    code="GEO-UNEXPECTED-TYPE",
                    issue_type="unexpected_geometry_type",
                    title="Unexpected Geometry Type",
                    message=f"{geometry.geom_type} is not allowed by the profile.",
                    severity=Severity.ERROR,
                    category="geometry",
                    recommendation=(
                        "Convert the feature to one of: "
                        + ", ".join(profile.expected_geometry_types)
                        + "."
                    ),
                    repair_risk=RepairRisk.REVIEW,
                    geometry_kind=_kind(geometry),
                    geometry_wkt=_wkt(geometry),
                    layer=layer,
                    feature_index=index,
                    check_name="geometry",
                )
            )
    return issues


def _attribute_issues(
    frame: gpd.GeoDataFrame, layer: str, rules: Sequence[AttributeRule]
) -> list[DatasetIssue]:
    issues: list[DatasetIssue] = []
    for rule in rules:
        if rule.column not in frame.columns:
            if rule.rule_type is AttributeRuleType.REQUIRED:
                issues.append(
                    _attribute_issue(rule, layer, None, Point(), "Required column is missing.")
                )
            continue
        series = frame[rule.column]
        positions: list[int] = []
        if rule.rule_type is AttributeRuleType.NOT_NULL:
            positions = [index for index, value in enumerate(series.isna()) if bool(value)]
        elif rule.rule_type is AttributeRuleType.UNIQUE:
            positions = [
                index for index, value in enumerate(series.duplicated(keep=False)) if bool(value)
            ]
        elif rule.rule_type is AttributeRuleType.ALLOWED_VALUES:
            positions = [
                index
                for index, value in enumerate(series)
                if not pd.isna(value) and value not in rule.allowed_values
            ]
        elif rule.rule_type is AttributeRuleType.NUMERIC_RANGE:
            positions = [
                index
                for index, value in enumerate(series)
                if not pd.isna(value)
                and (
                    not isinstance(value, (int, float))
                    or (rule.minimum is not None and float(value) < rule.minimum)
                    or (rule.maximum is not None and float(value) > rule.maximum)
                )
            ]
        for position in positions:
            issues.append(
                _attribute_issue(
                    rule,
                    layer,
                    position,
                    frame.geometry.iloc[position],
                    f"Column {rule.column!r} violates {rule.rule_type.value}.",
                )
            )
    return issues


def _attach_feature_ids(
    issues: Sequence[DatasetIssue], frame: gpd.GeoDataFrame, id_column: str | None
) -> list[DatasetIssue]:
    if id_column is None:
        return list(issues)
    if id_column not in frame.columns:
        raise ValueError(f"configured id_column {id_column!r} is missing")

    def identifier(position: int | None) -> str | int | None:
        if position is None:
            return None
        value = frame[id_column].iloc[position]
        if pd.isna(value):
            return None
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            return value
        return str(value)

    return [
        replace(
            issue,
            feature_id=identifier(issue.feature_index),
            related_feature_id=identifier(issue.related_feature_index),
        )
        for issue in issues
    ]


def _attribute_issue(
    rule: AttributeRule,
    layer: str,
    position: int | None,
    geometry: BaseGeometry,
    message: str,
) -> DatasetIssue:
    return DatasetIssue(
        code=f"ATTR-{rule.rule_type.value.upper()}",
        issue_type=rule.rule_type.value,
        title=rule.rule_type.value.replace("_", " ").title(),
        message=message,
        severity=rule.severity,
        category="attribute",
        recommendation=f"Correct column {rule.column!r} to satisfy the profile.",
        repair_risk=RepairRisk.NOT_REPAIRABLE,
        geometry_kind=_kind(geometry),
        geometry_wkt=_wkt(geometry),
        layer=layer,
        feature_index=position,
        metadata={"column": rule.column},
    )


def _crs_issues(frame: gpd.GeoDataFrame, layer: str, profile: QualityProfile) -> list[DatasetIssue]:
    geometry = next((item for item in frame.geometry if not item.is_empty), Point())
    if frame.crs is None and profile.require_crs:
        return [_metadata_issue(layer, geometry, "missing_crs", "Dataset CRS is required.")]
    if frame.crs is None:
        return []
    parsed = CRS.from_user_input(frame.crs)
    issues = []
    if profile.require_projected_crs and parsed.is_geographic:
        issues.append(
            _metadata_issue(layer, geometry, "geographic_crs", "Projected CRS is required.")
        )
    if profile.allowed_crs:
        allowed = {CRS.from_user_input(value) for value in profile.allowed_crs}
        if parsed not in allowed:
            issues.append(
                _metadata_issue(layer, geometry, "disallowed_crs", "CRS is not allowlisted.")
            )
    return issues


def _metadata_issue(
    layer: str, geometry: BaseGeometry, issue_type: str, message: str
) -> DatasetIssue:
    return DatasetIssue(
        code=f"META-{issue_type.upper()}",
        issue_type=issue_type,
        title=issue_type.replace("_", " ").title(),
        message=message,
        severity=Severity.ERROR,
        category="metadata",
        recommendation=(
            "Define a valid projected CRS, or transform to a CRS allowed by the quality profile."
        ),
        repair_risk=RepairRisk.NOT_REPAIRABLE,
        geometry_kind=_kind(geometry),
        geometry_wkt=_wkt(geometry),
        layer=layer,
    )
