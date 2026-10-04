"""Shapely/PyProj adapter for the high-level dataset QC workflow."""

from collections.abc import Mapping, Sequence

import geopandas as gpd  # type: ignore[import-untyped]
import shapely
from pyproj import CRS
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from geoqc.domain.models import (
    CategoryScore,
    CrsGuardResult,
    CrsUnitStatus,
    DatasetAuditResult,
    DatasetIssue,
    DatasetLayer,
    GeometryIssueType,
    IssueGeometryKind,
    QualityPreset,
    RepairRisk,
    ScoreDeduction,
    ScoringPolicy,
    TopologyRule,
    TopologyRuleType,
)
from geoqc.domain.models.spatial_intelligence import RoadIssueType, RoadNetworkConfig
from geoqc.domain.rules import Severity
from geoqc.infrastructure.gis.shapely_geometry_validator import ShapelyGeometryValidator
from geoqc.infrastructure.gis.shapely_spatial_intelligence import ShapelyRoadNetworkAnalyzer
from geoqc.infrastructure.gis.topology_rules_v2 import evaluate_advanced_rule

_GEOMETRY_DETAILS: Mapping[GeometryIssueType, tuple[str, str, Severity, RepairRisk]] = {
    GeometryIssueType.INVALID_GEOMETRY: (
        "Invalid geometry",
        "Repair the geometry and validate it again.",
        Severity.ERROR,
        RepairRisk.REVIEW,
    ),
    GeometryIssueType.EMPTY_GEOMETRY: (
        "Empty geometry",
        "Restore the missing geometry or remove the feature.",
        Severity.ERROR,
        RepairRisk.NOT_REPAIRABLE,
    ),
    GeometryIssueType.SELF_INTERSECTION: (
        "Self-intersection",
        "Preview a topology repair.",
        Severity.ERROR,
        RepairRisk.REVIEW,
    ),
    GeometryIssueType.RING_ERROR: (
        "Polygon ring error",
        "Preview an invalid-ring repair.",
        Severity.ERROR,
        RepairRisk.REVIEW,
    ),
    GeometryIssueType.DUPLICATE_VERTEX: (
        "Duplicate vertex",
        "Remove the duplicate vertex.",
        Severity.WARNING,
        RepairRisk.SAFE,
    ),
}


def assess_crs(crs: str | None, geometries: Sequence[BaseGeometry] = ()) -> CrsGuardResult:
    """Explain whether distance/area tolerances are safe for a CRS."""
    if crs is None or not str(crs).strip():
        return CrsGuardResult(
            None,
            CrsUnitStatus.UNKNOWN,
            None,
            False,
            "CRS is unknown; distance and area thresholds cannot be interpreted safely.",
        )
    try:
        parsed = CRS.from_user_input(crs)
    except Exception:
        return CrsGuardResult(
            str(crs),
            CrsUnitStatus.UNKNOWN,
            None,
            False,
            "CRS could not be parsed; verify the layer metadata before using tolerances.",
        )
    axes = parsed.axis_info
    unit = axes[0].unit_name if axes else None
    angular = bool(parsed.is_geographic)
    suggestion = _suggest_utm(geometries) if angular else None
    if angular:
        return CrsGuardResult(
            parsed.to_string(),
            CrsUnitStatus.WARNING,
            unit,
            True,
            "CRS uses angular units; distance and area tolerances are not metres.",
            suggestion,
        )
    return CrsGuardResult(
        parsed.to_string(),
        CrsUnitStatus.SAFE,
        unit,
        False,
        f"CRS uses projected {unit or 'linear'} units.",
    )


def audit_geometries(
    geometries: Sequence[BaseGeometry],
    *,
    dataset_name: str = "dataset",
    preset: QualityPreset | str | None = None,
    crs: str | None = None,
    tolerance: float = 0.0,
    minimum_area: float = 0.0,
    scoring: ScoringPolicy | None = None,
    profile_name: str | None = None,
) -> DatasetAuditResult:
    """Run an opinionated, plugin-ready quality audit over in-memory geometries."""
    if not dataset_name.strip():
        raise ValueError("dataset_name must not be empty")
    if tolerance < 0 or minimum_area < 0:
        raise ValueError("thresholds must be non-negative")
    items = tuple(_require_geometry(item) for item in geometries)
    selected = QualityPreset(preset) if preset is not None else None
    issues = list(_geometry_issues(items, dataset_name))
    if selected in {QualityPreset.PARCEL, QualityPreset.ADMIN_BOUNDARY}:
        issues.extend(_overlap_issues(items, dataset_name, tolerance=tolerance))
        issues.extend(_gap_issues(items, dataset_name, tolerance=tolerance))
        if minimum_area:
            issues.extend(_minimum_area_issues(items, dataset_name, minimum_area))
    elif selected is QualityPreset.ROAD:
        issues.extend(_road_issues(items, dataset_name, tolerance))
    elif selected is QualityPreset.POINT_SURVEY:
        issues.extend(_duplicate_issues(items, dataset_name, tolerance))
    ordered = tuple(sorted(issues, key=_issue_sort_key))
    scores, deductions, overall = score_issues(ordered, len(items), scoring)
    return DatasetAuditResult(
        dataset_name=dataset_name,
        preset=selected,
        feature_count=len(items),
        issues=ordered,
        crs_guard=assess_crs(crs, items),
        category_scores=scores,
        quality_score=overall,
        score_deductions=deductions,
        profile_name=profile_name,
    )


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


def issues_to_geodataframe(
    result: DatasetAuditResult,
    kind: IssueGeometryKind | str,
) -> gpd.GeoDataFrame:
    """Build one point/line/polygon issue layer with stable diagnostic fields."""
    selected = result.issues_for_layer(IssueGeometryKind(kind))
    records = [
        {
            "fingerprint": item.fingerprint,
            "check_name": item.check_name or item.category,
            "code": item.code,
            "issue_type": item.issue_type,
            "title": item.title,
            "message": item.message,
            "severity": item.severity.value,
            "category": item.category,
            "suggested_fix": item.recommendation,
            "recommendation": item.recommendation,
            "repair_risk": item.repair_risk.value,
            "source_layer": item.layer,
            "layer": item.layer,
            "feature_index": item.feature_index,
            "related_feature_index": item.related_feature_index,
            "feature_id": item.feature_id,
            "related_feature_id": item.related_feature_id,
            "geometry": shapely.from_wkt(item.geometry_wkt),
        }
        for item in selected
    ]
    columns = [
        "fingerprint",
        "check_name",
        "code",
        "issue_type",
        "title",
        "message",
        "severity",
        "category",
        "suggested_fix",
        "recommendation",
        "repair_risk",
        "source_layer",
        "layer",
        "feature_index",
        "related_feature_index",
        "feature_id",
        "related_feature_id",
        "geometry",
    ]
    output_crs = (
        result.crs_guard.crs if result.crs_guard.status is not CrsUnitStatus.UNKNOWN else None
    )
    return gpd.GeoDataFrame(records, columns=columns, geometry="geometry", crs=output_crs)


def _geometry_issues(items: Sequence[BaseGeometry], layer: str) -> list[DatasetIssue]:
    validator = ShapelyGeometryValidator()
    findings: list[DatasetIssue] = []
    for index, geometry in enumerate(items):
        for issue in validator.validate(geometry).issues:
            title, recommendation, severity, risk = _GEOMETRY_DETAILS[issue.issue_type]
            findings.append(
                _issue(
                    code=f"GEO-{issue.issue_type.value.upper()}",
                    issue_type=issue.issue_type.value,
                    title=title,
                    message=issue.message,
                    severity=severity,
                    category="geometry",
                    recommendation=recommendation,
                    risk=risk,
                    geometry=geometry,
                    layer=layer,
                    feature_index=index,
                )
            )
    return findings


def _overlap_issues(
    items: Sequence[BaseGeometry],
    layer: str,
    tolerance: float = 0.0,
    severity: Severity = Severity.ERROR,
) -> list[DatasetIssue]:
    findings: list[DatasetIssue] = []
    tree = STRtree(items) if items else None
    if tree is None:
        return findings
    for left, geometry in enumerate(items):
        if geometry.is_empty:
            continue
        for raw in tree.query(geometry):
            right = int(raw)
            if right <= left:
                continue
            overlap = geometry.intersection(items[right])
            if overlap.is_empty or overlap.area <= tolerance:
                continue
            findings.append(
                _issue(
                    code="TOP-NO-OVERLAP",
                    issue_type="overlap",
                    title="Overlapping features",
                    message=(
                        f"Features {left} and {right} overlap by {overlap.area:.6g} square units."
                    ),
                    severity=severity,
                    category="topology",
                    recommendation=(
                        "Review ownership, then trim one boundary or merge the features."
                    ),
                    risk=RepairRisk.DANGEROUS,
                    geometry=overlap,
                    layer=layer,
                    feature_index=left,
                    related_feature_index=right,
                    metadata={"overlap_area": float(overlap.area)},
                )
            )
    return findings


def _gap_issues(
    items: Sequence[BaseGeometry],
    layer: str,
    tolerance: float = 0.0,
    severity: Severity = Severity.WARNING,
) -> list[DatasetIssue]:
    polygonal = [
        item
        for item in items
        if item.geom_type in {"Polygon", "MultiPolygon"} and not item.is_empty
    ]
    if not polygonal:
        return []
    covered = shapely.union_all(polygonal)
    holes: list[Polygon] = []
    for polygon in _polygon_parts(covered):
        holes.extend(Polygon(ring) for ring in polygon.interiors)
    findings = []
    for hole in holes:
        if tolerance and hole.area > tolerance:
            continue
        findings.append(
            _issue(
                code="TOP-NO-GAP",
                issue_type="gap",
                title="Enclosed coverage gap",
                message=f"Coverage contains an enclosed gap of {hole.area:.6g} square units.",
                severity=severity,
                category="topology",
                recommendation="Review the surrounding boundaries before assigning the gap.",
                risk=RepairRisk.DANGEROUS,
                geometry=hole,
                layer=layer,
                metadata={"gap_area": float(hole.area)},
            )
        )
    return findings


def _duplicate_issues(
    items: Sequence[BaseGeometry],
    layer: str,
    tolerance: float = 0.0,
    severity: Severity = Severity.WARNING,
) -> list[DatasetIssue]:
    findings: list[DatasetIssue] = []
    tree = STRtree(items) if items else None
    if tree is None:
        return findings
    for left, geometry in enumerate(items):
        query = geometry.buffer(tolerance) if tolerance else geometry
        for raw in tree.query(query):
            right = int(raw)
            if right <= left:
                continue
            duplicate = (
                geometry.equals_exact(items[right], tolerance)
                if tolerance
                else geometry.equals(items[right])
            )
            if duplicate:
                findings.append(
                    _issue(
                        code="TOP-NO-DUPLICATE",
                        issue_type="duplicate_feature",
                        title="Duplicate feature",
                        message=f"Features {left} and {right} have duplicate geometry.",
                        severity=severity,
                        category="topology",
                        recommendation=(
                            "Confirm attributes, then remove or consolidate one feature."
                        ),
                        risk=RepairRisk.REVIEW,
                        geometry=geometry,
                        layer=layer,
                        feature_index=left,
                        related_feature_index=right,
                    )
                )
    return findings


def _minimum_area_issues(
    items: Sequence[BaseGeometry],
    layer: str,
    minimum: float,
    severity: Severity = Severity.WARNING,
) -> list[DatasetIssue]:
    return [
        _issue(
            code="TOP-MINIMUM-AREA",
            issue_type="below_minimum_area",
            title="Feature below minimum area",
            message=f"Feature {index} area {geometry.area:.6g} is below {minimum:.6g}.",
            severity=severity,
            category="topology",
            recommendation="Review whether the feature is a sliver, island, or valid small object.",
            risk=RepairRisk.REVIEW,
            geometry=geometry,
            layer=layer,
            feature_index=index,
            metadata={"area": float(geometry.area), "minimum_area": minimum},
        )
        for index, geometry in enumerate(items)
        if not geometry.is_empty and geometry.area < minimum
    ]


def _road_issues(items: Sequence[BaseGeometry], layer: str, tolerance: float) -> list[DatasetIssue]:
    if not items:
        return []
    config = RoadNetworkConfig(connection_tolerance=tolerance or 0.01)
    report = ShapelyRoadNetworkAnalyzer().analyze(tuple(_wkt(item) for item in items), config)
    findings = []
    for item in report.findings:
        risk = (
            RepairRisk.SAFE
            if item.issue_type is RoadIssueType.UNNODED_INTERSECTION
            else RepairRisk.REVIEW
        )
        findings.append(
            _issue(
                code=f"ROAD-{item.issue_type.value.upper()}",
                issue_type=item.issue_type.value,
                title=item.issue_type.value.replace("_", " ").title(),
                message=item.message,
                severity=Severity.WARNING,
                category="network",
                recommendation="Preview road-network repair and verify connectivity.",
                risk=risk,
                geometry=shapely.from_wkt(item.location_wkt),
                layer=layer,
                feature_index=item.feature_indices[0] if item.feature_indices else None,
                related_feature_index=item.feature_indices[1]
                if len(item.feature_indices) > 1
                else None,
                metadata={"metric": item.metric},
            )
        )
    return findings


def _cross_layer_issues(
    source: Sequence[BaseGeometry], reference: Sequence[BaseGeometry], rule: TopologyRule
) -> list[DatasetIssue]:
    reference_tree = STRtree(reference) if reference else None
    findings: list[DatasetIssue] = []
    for index, geometry in enumerate(source):
        candidates = (
            []
            if reference_tree is None
            else [int(value) for value in reference_tree.query(geometry)]
        )
        if rule.rule_type is TopologyRuleType.MUST_BE_INSIDE:
            valid = any(
                reference[item].buffer(rule.tolerance).covers(geometry) for item in candidates
            )
            if valid:
                continue
            issue_geometry = geometry
            title = "Feature outside reference layer"
            recommendation = f"Move or trim the feature into {rule.reference_layer}."
        else:
            hits = [item for item in candidates if geometry.intersects(reference[item])]
            if not hits:
                continue
            issue_geometry = shapely.union_all(
                [geometry.intersection(reference[item]) for item in hits]
            )
            title = "Forbidden layer intersection"
            recommendation = f"Review the conflict with {rule.reference_layer}."
        findings.append(
            _issue(
                code=f"TOP-{rule.rule_type.value.upper()}",
                issue_type=rule.rule_type.value,
                title=title,
                message=f"Feature {index} violates {rule.rule_type.value}.",
                severity=rule.severity,
                category="topology",
                recommendation=recommendation,
                risk=RepairRisk.DANGEROUS,
                geometry=issue_geometry,
                layer=rule.layer,
                feature_index=index,
            )
        )
    return findings


def _issue(
    *,
    code: str,
    issue_type: str,
    title: str,
    message: str,
    severity: Severity,
    category: str,
    recommendation: str,
    risk: RepairRisk,
    geometry: BaseGeometry,
    layer: str,
    feature_index: int | None = None,
    related_feature_index: int | None = None,
    metadata: Mapping[str, str | int | float | bool | None] | None = None,
) -> DatasetIssue:
    return DatasetIssue(
        code=code,
        issue_type=issue_type,
        title=title,
        message=message,
        severity=severity,
        category=category,
        recommendation=recommendation,
        repair_risk=risk,
        geometry_kind=_geometry_kind(geometry),
        geometry_wkt=_wkt(geometry),
        layer=layer,
        feature_index=feature_index,
        related_feature_index=related_feature_index,
        metadata=metadata or {},
    )


def score_issues(
    issues: Sequence[DatasetIssue],
    feature_count: int,
    policy: ScoringPolicy | None = None,
) -> tuple[tuple[CategoryScore, ...], tuple[ScoreDeduction, ...], float]:
    """Score findings with size-normalized penalties and explain every deduction."""
    selected_policy = policy or ScoringPolicy()
    if feature_count < 0:
        raise ValueError("feature_count must be non-negative")
    denominator = max(1, feature_count)
    scores: list[CategoryScore] = []
    deductions: list[ScoreDeduction] = []
    for category in selected_policy.category_weights:
        category_issues = [item for item in issues if item.category == category]
        points = 0.0
        entity_points: dict[tuple[int | None, int | None], float] = {}
        for issue in category_issues:
            affected = (
                len(set(issue.feature_indices)) / denominator if issue.feature_indices else 1.0
            )
            raw = selected_policy.severity_penalties[issue.severity] * min(1.0, affected)
            entity = (issue.feature_index, issue.related_feature_index)
            entity_remaining = max(
                0.0,
                selected_policy.repeated_feature_cap - entity_points.get(entity, 0.0),
            )
            category_remaining = max(0.0, selected_policy.category_caps[category] - points)
            deduction = min(raw, entity_remaining, category_remaining)
            entity_points[entity] = entity_points.get(entity, 0.0) + deduction
            points += deduction
            deductions.append(
                ScoreDeduction(
                    category=category,
                    issue_fingerprint=issue.fingerprint,
                    severity=issue.severity,
                    points=round(deduction, 4),
                    explanation=(
                        f"{issue.title}: {issue.severity.value} base penalty "
                        f"{selected_policy.severity_penalties[issue.severity]:g} × "
                        f"affected proportion {affected:.6f}; bounded by the "
                        f"{selected_policy.repeated_feature_cap:g}-point repeated-feature "
                        f"cap and {selected_policy.category_caps[category]:g}-point category cap."
                    ),
                )
            )
        scores.append(
            CategoryScore(category, round(max(0.0, 100.0 - points), 2), len(category_issues))
        )
    weight_total = sum(selected_policy.category_weights.values())
    score_by_category = {item.category: item.score for item in scores}
    overall = (
        sum(
            score_by_category[category] * weight
            for category, weight in selected_policy.category_weights.items()
        )
        / weight_total
    )
    return tuple(scores), tuple(deductions), round(overall, 2)


def _geometry_kind(geometry: BaseGeometry) -> IssueGeometryKind:
    dimension = shapely.get_dimensions(geometry)
    if dimension >= 2:
        return IssueGeometryKind.POLYGON
    if dimension == 1:
        return IssueGeometryKind.LINE
    return IssueGeometryKind.POINT


def _polygon_parts(geometry: BaseGeometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        return [part for item in geometry.geoms for part in _polygon_parts(item)]
    return []


def _suggest_utm(geometries: Sequence[BaseGeometry]) -> str | None:
    non_empty = [item for item in geometries if not item.is_empty]
    if not non_empty:
        return None
    center = shapely.union_all(non_empty).centroid
    if not (-180 <= center.x <= 180 and -90 <= center.y <= 90):
        return None
    zone = min(60, max(1, int((center.x + 180) // 6) + 1))
    return f"EPSG:{32600 + zone if center.y >= 0 else 32700 + zone}"


def _issue_sort_key(issue: DatasetIssue) -> tuple[object, ...]:
    return (
        issue.category,
        issue.issue_type,
        issue.layer or "",
        issue.feature_index or -1,
        issue.related_feature_index or -1,
        issue.geometry_wkt,
    )


def _require_geometry(value: BaseGeometry) -> BaseGeometry:
    if not isinstance(value, BaseGeometry):
        raise TypeError("every item must be a Shapely BaseGeometry")
    return value


def _wkt(geometry: BaseGeometry) -> str:
    return str(shapely.to_wkt(geometry, rounding_precision=-1))
