"""GeoPandas serialization for canonical audit findings."""

import geopandas as gpd  # type: ignore[import-untyped]
import shapely

from geoqc.domain.models import CrsUnitStatus, DatasetAuditResult, IssueGeometryKind


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
