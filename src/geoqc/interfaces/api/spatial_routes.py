"""Spatial intelligence and repair-priority HTTP routes."""

from dataclasses import asdict

import shapely
from fastapi import APIRouter, HTTPException

from geoqc import ConflictPolicy, PriorityWeights, SpatialDuplicateConfig, analyze_spatial_conflicts, compare_datasets, detect_spatial_duplicates, prioritize_repairs
from geoqc.interfaces.api.request_models import DatasetComparisonRequest, RepairPriorityRequest, SpatialConflictRequest, SpatialDuplicateRequest

router = APIRouter()

@router.post("/api/spatial/duplicates")
def spatial_duplicates(payload: SpatialDuplicateRequest) -> dict[str, object]:
    """Return indexed IoU, Hausdorff, and shape-similarity duplicate findings."""
    try:
        geometries = [shapely.from_wkt(value) for value in payload.geometries_wkt]
        report = detect_spatial_duplicates(
            geometries,
            SpatialDuplicateConfig(
                similarity_threshold=payload.similarity_threshold,
                search_tolerance=payload.search_tolerance,
                maximum_pairs=payload.maximum_pairs,
            ),
        )
        return asdict(report)
    except (TypeError, ValueError, shapely.errors.GEOSException) as error:
        raise HTTPException(
            status_code=422, detail="Invalid duplicate-analysis payload."
        ) from error

@router.post("/api/spatial/compare")
def spatial_compare(payload: DatasetComparisonRequest) -> dict[str, object]:
    """Return geometry, attribute, CRS, schema, and boundary differences."""
    try:
        return asdict(
            compare_datasets(
                payload.left.to_domain(),
                payload.right.to_domain(),
                match_threshold=payload.match_threshold,
            )
        )
    except (TypeError, ValueError, shapely.errors.GEOSException) as error:
        raise HTTPException(
            status_code=422, detail="Invalid dataset-comparison payload."
        ) from error

@router.post("/api/spatial/conflicts")
def spatial_conflicts(payload: SpatialConflictRequest) -> dict[str, object]:
    """Return semantic cross-layer conflicts and severity scores."""
    try:
        report = analyze_spatial_conflicts(
            [item.to_domain() for item in payload.layers], ConflictPolicy()
        )
        return asdict(report)
    except (TypeError, ValueError, shapely.errors.GEOSException) as error:
        raise HTTPException(status_code=422, detail="Invalid conflict-analysis payload.") from error

@router.post("/api/repairs/prioritize")
def repair_priorities(payload: RepairPriorityRequest) -> dict[str, object]:
    """Rank repair work using rules only; no AI or LLM is invoked."""
    recommendations = prioritize_repairs(
        [item.to_domain() for item in payload.candidates], PriorityWeights()
    )
    return {"recommendations": [asdict(item) for item in recommendations]}
