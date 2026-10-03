"""File, GeoDataFrame, profile, output, and repair-plan QC orchestration."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from math import isnan
from pathlib import Path
from typing import Any
from uuid import uuid4

import geopandas as gpd  # type: ignore[import-untyped]
import pandas as pd
import pyogrio  # type: ignore[import-untyped]
import shapely
import yaml  # type: ignore[import-untyped]
from pyproj import CRS
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from geoqc.domain.models import (
    AttributeOverlapPolicy,
    AttributeRule,
    AttributeRuleType,
    DatasetAuditResult,
    DatasetIssue,
    DatasetLayer,
    IssueGeometryKind,
    QualityGatePolicy,
    QualityPreset,
    QualityProfile,
    RepairPlan,
    RepairPlanAction,
    RepairPlanConflict,
    RepairRisk,
    ScoringPolicy,
    TopologyRule,
    TopologyRuleType,
    WorkflowArtifacts,
)
from geoqc.domain.rules import Severity
from geoqc.infrastructure.gis.quality_workflow import (
    audit_dataset,
    evaluate_topology_rules,
    issues_to_geodataframe,
    score_issues,
)

_SUPPORTED_SUFFIXES = frozenset({".fgb", ".geojson", ".gpkg", ".json", ".parquet", ".shp"})
_STRATEGIES = {
    "duplicate_vertex": "remove_duplicate_vertices",
    "invalid_geometry": "make_valid",
    "self_intersection": "make_valid",
    "ring_error": "repair_ring",
    "overlap": "resolve_overlap_by_policy",
    "gap": "assign_gap_by_policy",
    "broken_connection": "snap_endpoint",
    "unnoded_intersection": "node_intersection",
    "duplicate_segment": "remove_duplicate_segment",
}


def load_quality_profile(source: str | Path) -> QualityProfile:
    """Load and validate a versioned JSON or YAML quality profile."""
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.casefold() == ".json":
        raw = json.loads(text)
    elif path.suffix.casefold() in {".yaml", ".yml"}:
        raw = yaml.safe_load(text)
    else:
        raise ValueError("quality profile must use .json, .yaml, or .yml")
    if not isinstance(raw, dict):
        raise ValueError("quality profile root must be an object")
    return quality_profile_from_dict(raw)


def quality_profile_from_dict(raw: Mapping[str, object]) -> QualityProfile:
    """Validate a mapping and build an immutable quality profile."""
    allowed = {
        "name",
        "id_column",
        "version",
        "preset",
        "tolerance",
        "minimum_area",
        "crs",
        "topology_rules",
        "attribute_rules",
        "scoring",
        "quality_gate",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"unknown quality profile fields: {unknown}")
    crs = _mapping(raw.get("crs", {}), "crs")
    scoring_raw = _mapping(raw.get("scoring", {}), "scoring")
    gate_raw = _mapping(raw.get("quality_gate", {}), "quality_gate")
    weights = scoring_raw.get("category_weights")
    penalties = scoring_raw.get("severity_penalties")
    scoring = ScoringPolicy(
        category_weights=(
            {
                str(key): _number(value, f"category weight {key}")
                for key, value in _mapping(weights, "category_weights").items()
            }
            if weights is not None
            else ScoringPolicy().category_weights
        ),
        severity_penalties=(
            {
                Severity(str(key)): _number(value, f"severity penalty {key}")
                for key, value in _mapping(penalties, "severity_penalties").items()
            }
            if penalties is not None
            else ScoringPolicy().severity_penalties
        ),
    )
    return QualityProfile(
        name=str(raw.get("name", "")).strip(),
        version=_integer(raw.get("version", 1), "version"),
        preset=QualityPreset(str(raw["preset"])) if raw.get("preset") is not None else None,
        tolerance=_number(raw.get("tolerance", 0.0), "tolerance"),
        minimum_area=_number(raw.get("minimum_area", 0.0), "minimum_area"),
        require_crs=bool(crs.get("required", True)),
        require_projected_crs=bool(crs.get("require_projected", False)),
        allowed_crs=tuple(str(item) for item in _sequence(crs.get("allowed", ()), "crs.allowed")),
        id_column=str(raw["id_column"]) if raw.get("id_column") is not None else None,
        topology_rules=tuple(
            _topology_rule(_mapping(item, "topology rule"))
            for item in _sequence(raw.get("topology_rules", ()), "topology_rules")
        ),
        attribute_rules=tuple(
            _attribute_rule(_mapping(item, "attribute rule"))
            for item in _sequence(raw.get("attribute_rules", ()), "attribute_rules")
        ),
        scoring=scoring,
        gate=QualityGatePolicy(
            minimum_score=_number(gate_raw.get("minimum_score", 75.0), "minimum_score"),
            fail_on=Severity(str(gate_raw.get("fail_on", "error"))),
            allow_unknown_crs=bool(gate_raw.get("allow_unknown_crs", False)),
        ),
    )


def dump_quality_profile(profile: QualityProfile, destination: str | Path) -> Path:
    """Write a profile as deterministic JSON or YAML."""
    path = Path(destination)
    payload = _profile_dict(profile)
    if path.suffix.casefold() == ".json":
        text = json.dumps(payload, indent=2, sort_keys=True)
    elif path.suffix.casefold() in {".yaml", ".yml"}:
        text = yaml.safe_dump(payload, sort_keys=False)
    else:
        raise ValueError("quality profile must use .json, .yaml, or .yml")
    _atomic_text(path, text)
    return path


def audit_geodataframe(
    frame: gpd.GeoDataFrame,
    *,
    dataset_name: str = "dataset",
    profile: QualityProfile | None = None,
    preset: QualityPreset | str | None = None,
) -> DatasetAuditResult:
    """Run geometry, topology, CRS, and attribute checks in one workflow."""
    if not isinstance(frame, gpd.GeoDataFrame):
        raise TypeError("frame must be a GeoDataFrame")
    if frame.geometry.name not in frame.columns:
        raise ValueError("frame must have an active geometry column")
    selected_preset = profile.preset if profile is not None else preset
    crs = frame.crs.to_string() if frame.crs is not None else None
    base = audit_dataset(
        tuple(frame.geometry),
        dataset_name=dataset_name,
        preset=selected_preset,
        crs=crs,
        tolerance=profile.tolerance if profile else 0.0,
        minimum_area=profile.minimum_area if profile else 0.0,
        scoring=profile.scoring if profile else None,
        profile_name=profile.name if profile else None,
    )
    issues = list(base.issues)
    if profile is not None:
        issues.extend(_attribute_issues(frame, dataset_name, profile.attribute_rules))
        issues.extend(_crs_issues(frame, dataset_name, profile))
        local_rules = tuple(
            rule
            for rule in profile.topology_rules
            if rule.layer == dataset_name and rule.reference_layer is None
        )
        if local_rules:
            layer = DatasetLayer(
                dataset_name,
                tuple(_wkt(item) for item in frame.geometry),
                crs,
                _feature_attributes(frame),
            )
            issues.extend(evaluate_topology_rules((layer,), local_rules))
        issues = _attach_feature_ids(issues, frame, profile.id_column)
    return _rebuild_result(base, issues, profile.scoring if profile else None)


def audit_file(
    source: str | Path,
    *,
    layer: str | None = None,
    profile: QualityProfile | None = None,
    preset: QualityPreset | str | None = None,
) -> DatasetAuditResult:
    """Read one supported vector dataset and run the unified audit."""
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.casefold() not in _SUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported dataset format: {path.suffix}")
    selected_layer = layer
    if path.suffix.casefold() == ".gpkg":
        layers = [str(item[0]) for item in pyogrio.list_layers(path)]
        if selected_layer is None and len(layers) > 1:
            raise ValueError("GeoPackage contains multiple layers; specify layer")
        if selected_layer is not None and selected_layer not in layers:
            raise ValueError(f"unknown layer {selected_layer!r}; available layers: {layers}")
        selected_layer = selected_layer or layers[0]
    if path.suffix.casefold() == ".parquet":
        frame = gpd.read_parquet(path)
    else:
        frame = gpd.read_file(path, layer=selected_layer)
    return audit_geodataframe(
        frame,
        dataset_name=selected_layer or path.stem,
        profile=profile,
        preset=preset,
    )


def audit_layers(
    frames: Mapping[str, gpd.GeoDataFrame], *, profile: QualityProfile
) -> DatasetAuditResult:
    """Audit multiple named layers and include configured cross-layer rules."""
    if not frames:
        raise ValueError("at least one layer is required")
    results = [
        audit_geodataframe(frame, dataset_name=name, profile=profile)
        for name, frame in frames.items()
    ]
    layers = tuple(
        DatasetLayer(
            name,
            tuple(_wkt(item) for item in frame.geometry),
            frame.crs.to_string() if frame.crs is not None else None,
            _feature_attributes(frame),
        )
        for name, frame in frames.items()
    )
    cross_rules = tuple(rule for rule in profile.topology_rules if rule.reference_layer is not None)
    issues = [issue for result in results for issue in result.issues]
    issues.extend(evaluate_topology_rules(layers, cross_rules))
    first = results[0]
    combined = DatasetAuditResult(
        dataset_name=profile.name,
        preset=profile.preset,
        feature_count=sum(result.feature_count for result in results),
        issues=(),
        crs_guard=first.crs_guard,
        category_scores=(),
        quality_score=100.0,
        profile_name=profile.name,
    )
    return _rebuild_result(combined, issues, profile.scoring)


def write_issue_layers(
    result: DatasetAuditResult,
    destination: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Atomically write point, line, and polygon findings to one GeoPackage."""
    path = Path(destination)
    if path.suffix.casefold() != ".gpkg":
        raise ValueError("issue dataset must use .gpkg")
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.{uuid4().hex}.tmp.gpkg")
    try:
        wrote = False
        for kind in IssueGeometryKind:
            frame = issues_to_geodataframe(result, kind)
            if frame.empty:
                continue
            frame.to_file(temporary, layer=f"geoqc_errors_{kind.value}", driver="GPKG")
            wrote = True
        if not wrote:
            empty = gpd.GeoDataFrame(
                {"status": pd.Series(dtype="str")},
                geometry=gpd.GeoSeries([], dtype="geometry", crs=result.crs_guard.crs),
            )
            empty.to_file(temporary, layer="geoqc_errors_point", driver="GPKG")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def build_repair_plan(result: DatasetAuditResult) -> RepairPlan:
    """Build an explainable plan and flag competing non-safe actions per feature."""
    actions = tuple(
        RepairPlanAction(
            issue_fingerprint=issue.fingerprint,
            feature_index=issue.feature_index,
            issue_type=issue.issue_type,
            strategy=_STRATEGIES.get(issue.issue_type, "manual_review"),
            risk=issue.repair_risk,
            automatic=issue.repair_risk is RepairRisk.SAFE,
        )
        for issue in result.issues
        if issue.issue_type in _STRATEGIES
    )
    by_feature: dict[int | None, list[RepairPlanAction]] = {}
    for action in actions:
        by_feature.setdefault(action.feature_index, []).append(action)
    conflicts = tuple(
        RepairPlanConflict(
            feature_index=feature_index,
            issue_fingerprints=tuple(item.issue_fingerprint for item in selected),
            reason="Multiple reviewed repair strategies target the same feature.",
        )
        for feature_index, selected in by_feature.items()
        if feature_index is not None
        and len([item for item in selected if item.risk is not RepairRisk.SAFE]) > 1
    )
    return RepairPlan(actions, conflicts)


def write_audit_report(result: DatasetAuditResult, destination: str | Path) -> Path:
    """Write JSON or self-contained HTML directly from a unified audit result."""
    path = Path(destination)
    if path.suffix.casefold() == ".json":
        _atomic_text(path, json.dumps(result.to_dict(), indent=2))
        return path
    if path.suffix.casefold() == ".html":
        from geoqc import build_quality_report
        from geoqc.infrastructure.reporting import HtmlReportRenderer

        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            HtmlReportRenderer().write(build_quality_report(result), temporary)
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return path
    raise ValueError("audit report must use .json or .html")


def run_quality_workflow(
    source: str | Path,
    *,
    profile: QualityProfile,
    layer: str | None = None,
    issue_output: str | Path | None = None,
    report_output: str | Path | None = None,
    overwrite: bool = False,
) -> WorkflowArtifacts:
    """Run audit and optional outputs with one package-level call."""
    result = audit_file(source, layer=layer, profile=profile)
    issues = write_issue_layers(result, issue_output, overwrite=overwrite) if issue_output else None
    report = write_audit_report(result, report_output) if report_output else None
    return WorkflowArtifacts(
        result=result,
        issue_dataset=str(issues.resolve()) if issues else None,
        report=str(report.resolve()) if report else None,
    )


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
        recommendation="Assign or transform to a CRS allowed by the quality profile.",
        repair_risk=RepairRisk.NOT_REPAIRABLE,
        geometry_kind=_kind(geometry),
        geometry_wkt=_wkt(geometry),
        layer=layer,
    )


def _rebuild_result(
    base: DatasetAuditResult, issues: Sequence[DatasetIssue], scoring: ScoringPolicy | None
) -> DatasetAuditResult:
    unique = {
        (
            item.fingerprint,
            item.code,
            item.feature_index,
            item.related_feature_index,
            item.geometry_wkt,
        ): item
        for item in issues
    }
    ordered = tuple(sorted(unique.values(), key=lambda item: (item.category, item.fingerprint)))
    scores, deductions, overall = score_issues(ordered, base.feature_count, scoring)
    return DatasetAuditResult(
        dataset_name=base.dataset_name,
        preset=base.preset,
        feature_count=base.feature_count,
        issues=ordered,
        crs_guard=base.crs_guard,
        category_scores=scores,
        quality_score=overall,
        score_deductions=deductions,
        profile_name=base.profile_name,
        schema_version=base.schema_version,
    )


def _topology_rule(raw: Mapping[str, object]) -> TopologyRule:
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
        "attribute_rules": [
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
        return float(value)
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error


def _integer(value: object, name: str) -> int:
    number = _number(value, name)
    if not number.is_integer():
        raise ValueError(f"{name} must be an integer")
    return int(number)


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _kind(geometry: BaseGeometry) -> IssueGeometryKind:
    dimensions = shapely.get_dimensions(geometry)
    if dimensions >= 2:
        return IssueGeometryKind.POLYGON
    if dimensions == 1:
        return IssueGeometryKind.LINE
    return IssueGeometryKind.POINT


def _wkt(geometry: BaseGeometry) -> str:
    return str(shapely.to_wkt(geometry, rounding_precision=-1))


def _feature_attributes(
    frame: gpd.GeoDataFrame,
) -> tuple[Mapping[str, str | int | float | bool | None], ...]:
    columns = [column for column in frame.columns if column != frame.geometry.name]
    records: list[Mapping[str, str | int | float | bool | None]] = []
    for raw in frame[columns].to_dict(orient="records"):
        records.append({str(key): _attribute_value(value) for key, value in raw.items()})
    return tuple(records)


def _attribute_value(value: object) -> str | int | float | bool | None:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and isnan(value):
            return None
        return value
    item = getattr(value, "item", None)
    if callable(item):
        normalized = item()
        if isinstance(normalized, (str, int, float, bool)):
            return normalized
    return str(value)
