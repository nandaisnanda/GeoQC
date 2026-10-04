"""Canonical in-memory geometry audit orchestration."""

from collections.abc import Sequence

from shapely.geometry.base import BaseGeometry

from geoqc.application.scoring_service import score_issues
from geoqc.domain.models import DatasetAuditResult, QualityPreset, ScoringPolicy
from geoqc.infrastructure.gis.crs_analysis import assess_crs
from geoqc.infrastructure.gis.finding_builders import (
    _duplicate_issues,
    _gap_issues,
    _geometry_issues,
    _issue_sort_key,
    _minimum_area_issues,
    _overlap_issues,
    _require_geometry,
    _road_issues,
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
