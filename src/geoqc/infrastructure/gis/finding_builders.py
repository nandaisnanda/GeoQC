"""Shapely-backed builders for canonical dataset findings."""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import geopandas as gpd  # type: ignore[import-untyped]
import numpy as np
import shapely
from pyproj import CRS, Transformer
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
from geoqc.infrastructure.gis.spatial_helpers import (
    _has_finite_coordinates,
    _is_valid,
    _safe_buffer,
)

_ROAD_GEOMETRY_TYPES = frozenset({"LineString", "MultiLineString"})
_SPECIFIC_INVALID_TYPES = frozenset(
    {
        GeometryIssueType.EMPTY_GEOMETRY,
        GeometryIssueType.SELF_INTERSECTION,
        GeometryIssueType.RING_ERROR,
    }
)

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
        detected = validator.validate(geometry).issues
        # One finding per root cause: the generic invalid finding is redundant
        # when a specific defect already explains the invalidity.
        if any(issue.issue_type in _SPECIFIC_INVALID_TYPES for issue in detected):
            detected = tuple(
                issue
                for issue in detected
                if issue.issue_type is not GeometryIssueType.INVALID_GEOMETRY
            )
        for issue in detected:
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


@dataclass(frozen=True, slots=True)
class _AreaUnits:
    """Formats areas in CRS units, or in metres through UTM for a geographic CRS."""

    unit: str
    note: str = ""
    project: Callable[[BaseGeometry], BaseGeometry] | None = None

    def text(self, geometry: BaseGeometry) -> str:
        measured = self.project(geometry) if self.project is not None else geometry
        return f"{measured.area:.6g} {self.unit}{self.note}"


_AREA_UNIT_NAMES = {
    "metre": "m²",
    "meter": "m²",
    "foot": "ft²",
    "US survey foot": "US ft²",
}


def _area_units(items: Sequence[BaseGeometry], crs: str | None) -> _AreaUnits:
    if crs is None:
        return _AreaUnits("square units")
    parsed = CRS.from_user_input(crs)
    if not parsed.is_geographic:
        unit = parsed.axis_info[0].unit_name if parsed.axis_info else ""
        return _AreaUnits(_AREA_UNIT_NAMES.get(unit, f"square {unit or 'units'}"))
    finite = [item for item in items if not item.is_empty and _has_finite_coordinates(item)]
    try:
        utm = gpd.GeoSeries(finite, crs=parsed).estimate_utm_crs() if finite else None
    except RuntimeError:
        # Coordinates outside the lon/lat range have no UTM zone.
        utm = None
    if utm is None:
        return _AreaUnits("square degrees")
    transformer = Transformer.from_crs(parsed, utm, always_xy=True)
    return _AreaUnits(
        "m²",
        f" (measured in {utm.to_string()}; the dataset CRS is geographic)",
        lambda geometry: shapely.transform(
            geometry, lambda xy: np.column_stack(transformer.transform(xy[:, 0], xy[:, 1]))
        ),
    )


def _overlap_issues(
    items: Sequence[BaseGeometry],
    layer: str,
    tolerance: float = 0.0,
    severity: Severity = Severity.ERROR,
    crs: str | None = None,
) -> list[DatasetIssue]:
    findings: list[DatasetIssue] = []
    tree = STRtree(items) if items else None
    if tree is None:
        return findings
    units: _AreaUnits | None = None
    for left, geometry in enumerate(items):
        # Invalid geometries are reported by the geometry checks; GEOS overlay
        # operations can raise on them, so they are excluded here.
        if geometry.is_empty or not _is_valid(geometry):
            continue
        for raw in tree.query(geometry):
            right = int(raw)
            if right <= left or not _is_valid(items[right]):
                continue
            overlap = geometry.intersection(items[right])
            if overlap.is_empty or overlap.area <= tolerance:
                continue
            units = units or _area_units(items, crs)
            findings.append(
                _issue(
                    code="TOP-NO-OVERLAP",
                    issue_type="overlap",
                    title="Overlapping features",
                    message=(f"Features {left} and {right} overlap by {units.text(overlap)}."),
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
    crs: str | None = None,
) -> list[DatasetIssue]:
    polygonal = [
        item
        for item in items
        if item.geom_type in {"Polygon", "MultiPolygon"} and not item.is_empty and _is_valid(item)
    ]
    if not polygonal:
        return []
    covered = shapely.union_all(polygonal)
    holes: list[Polygon] = []
    for polygon in _polygon_parts(covered):
        holes.extend(Polygon(ring) for ring in polygon.interiors)
    findings = []
    units = _area_units(polygonal, crs) if holes else None
    for hole in holes:
        if tolerance and hole.area > tolerance:
            continue
        assert units is not None
        findings.append(
            _issue(
                code="TOP-NO-GAP",
                issue_type="gap",
                title="Enclosed coverage gap",
                message=f"Coverage contains an enclosed gap of {units.text(hole)}.",
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
    finite = [_has_finite_coordinates(item) for item in items]
    for left, geometry in enumerate(items):
        query = _safe_buffer(geometry, tolerance) if tolerance else geometry
        if not finite[left] or query is None:
            continue
        for raw in tree.query(query):
            right = int(raw)
            if right <= left or not finite[right]:
                continue
            if tolerance:
                duplicate = geometry.equals_exact(items[right], tolerance)
            else:
                try:
                    duplicate = geometry.equals(items[right])
                except shapely.errors.GEOSException:
                    # Topological equality raises on degenerate rings; compare
                    # coordinates instead.
                    duplicate = geometry.equals_exact(items[right], 0.0)
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
    crs: str | None = None,
) -> list[DatasetIssue]:
    flagged = [
        (index, geometry)
        for index, geometry in enumerate(items)
        # Invalid geometries are reported by the geometry checks; their area is unreliable.
        if not geometry.is_empty and _is_valid(geometry) and geometry.area < minimum
    ]
    if not flagged:
        return []
    units = _area_units(items, crs)
    # The threshold is compared in CRS units even when the message reports metres.
    threshold_unit = "square degrees" if units.project is not None else units.unit
    return [
        _issue(
            code="TOP-MINIMUM-AREA",
            issue_type="below_minimum_area",
            title="Feature below minimum area",
            message=(
                f"Feature {index} area {units.text(geometry)} is below "
                f"{minimum:.6g} {threshold_unit}."
            ),
            severity=severity,
            category="topology",
            recommendation="Review whether the feature is a sliver, island, or valid small object.",
            risk=RepairRisk.REVIEW,
            geometry=geometry,
            layer=layer,
            feature_index=index,
            metadata={"area": float(geometry.area), "minimum_area": minimum},
        )
        for index, geometry in flagged
    ]


def _sliver_issues(
    items: Sequence[BaseGeometry],
    layer: str,
    crs: str | None,
    minimum_area: float = 1.0,
    compactness: float = 0.05,
) -> list[DatasetIssue]:
    """Flag polygons under ``minimum_area`` m² or thinner than ``compactness`` (4πA/P²)."""
    units = _area_units(items, crs)
    if units.unit != "m²":
        # No metric CRS and no UTM zone: areas would be meaningless.
        return []
    findings = []
    for index, geometry in enumerate(items):
        if geometry.is_empty or not _is_valid(geometry) or geometry.geom_type not in _POLYGONAL:
            continue
        measured = units.project(geometry) if units.project is not None else geometry
        area, perimeter = measured.area, measured.length
        thin = perimeter > 0 and 4 * math.pi * area / perimeter**2 < compactness
        if area >= minimum_area and not thin:
            continue
        findings.append(
            _issue(
                code="TOP-SLIVER",
                issue_type="sliver_polygon",
                title="Sliver polygon",
                message=(
                    f"Feature {index} is a sliver: area {area:.6g} m², "
                    f"perimeter {perimeter:.6g} m{units.note}."
                ),
                severity=Severity.WARNING,
                category="topology",
                recommendation="Review whether the feature is a sliver or a valid small object.",
                risk=RepairRisk.REVIEW,
                geometry=geometry,
                layer=layer,
                feature_index=index,
                metadata={"area": float(area), "perimeter": float(perimeter)},
            )
        )
    return findings


_POLYGONAL = frozenset({"Polygon", "MultiPolygon"})


def _road_issues(items: Sequence[BaseGeometry], layer: str, tolerance: float) -> list[DatasetIssue]:
    findings = [
        _issue(
            code="GEO-UNEXPECTED-TYPE",
            issue_type="unexpected_geometry_type",
            title="Unexpected Geometry Type",
            message=f"{geometry.geom_type} is not allowed by the road preset.",
            severity=Severity.ERROR,
            category="geometry",
            recommendation="Convert the feature to one of: LineString, MultiLineString.",
            risk=RepairRisk.REVIEW,
            geometry=geometry,
            layer=layer,
            feature_index=index,
        )
        for index, geometry in enumerate(items)
        if geometry.geom_type not in _ROAD_GEOMETRY_TYPES
    ]
    config = RoadNetworkConfig(connection_tolerance=tolerance or 0.01)
    # NaN coordinates are reported as invalid geometry, and coordinates near the
    # float limit overflow inside buffer. Both would break the analyzer.
    owners = [
        index
        for index, geometry in enumerate(items)
        if geometry.geom_type in _ROAD_GEOMETRY_TYPES
        and _safe_buffer(geometry, config.connection_tolerance) is not None
    ]
    if not owners:
        return findings
    report = ShapelyRoadNetworkAnalyzer().analyze(
        tuple(_wkt(items[index]) for index in owners), config
    )
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
                feature_index=owners[item.feature_indices[0]] if item.feature_indices else None,
                related_feature_index=owners[item.feature_indices[1]]
                if len(item.feature_indices) > 1
                else None,
                metadata={"metric": item.metric},
            )
        )
    return findings


def _safe_intersects(left: BaseGeometry, right: BaseGeometry) -> bool:
    """Intersection test that treats a GEOS failure on extreme coordinates as no hit."""
    try:
        return bool(left.intersects(right))
    except shapely.errors.GEOSException:
        return False


def _cross_layer_issues(
    source: Sequence[BaseGeometry], reference: Sequence[BaseGeometry], rule: TopologyRule
) -> list[DatasetIssue]:
    reference_tree = STRtree(reference) if reference else None
    finite_reference = [_has_finite_coordinates(item) for item in reference]
    findings: list[DatasetIssue] = []
    for index, geometry in enumerate(source):
        if not _has_finite_coordinates(geometry):
            continue
        candidates = (
            []
            if reference_tree is None
            else [
                int(value)
                for value in reference_tree.query(geometry)
                if finite_reference[int(value)]
            ]
        )
        if rule.rule_type is TopologyRuleType.MUST_BE_INSIDE:
            valid = any(
                buffered.covers(geometry)
                for item in candidates
                if (buffered := _safe_buffer(reference[item], rule.tolerance)) is not None
            )
            if valid:
                continue
            issue_geometry = geometry
            title = "Feature outside reference layer"
            recommendation = f"Move or trim the feature into {rule.reference_layer}."
        else:
            hits = [item for item in candidates if _safe_intersects(geometry, reference[item])]
            if not hits:
                continue
            # Overlay needs valid input. Invalid features still violate the rule, so
            # report them at the source geometry instead of the intersection.
            issue_geometry = (
                shapely.union_all([geometry.intersection(reference[item]) for item in hits])
                if _is_valid(geometry) and all(_is_valid(reference[item]) for item in hits)
                else geometry
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
