"""Shapely-backed builders for canonical dataset findings."""

from collections.abc import Mapping, Sequence

import shapely
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from geoqc.domain.models import (
    DatasetIssue,
    GeometryIssueType,
    IssueGeometryKind,
    RepairRisk,
    TopologyRule,
    TopologyRuleType,
)
from geoqc.domain.models.spatial_intelligence import RoadIssueType, RoadNetworkConfig
from geoqc.domain.rules import Severity
from geoqc.infrastructure.gis.shapely_geometry_validator import ShapelyGeometryValidator
from geoqc.infrastructure.gis.shapely_spatial_intelligence import ShapelyRoadNetworkAnalyzer

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
