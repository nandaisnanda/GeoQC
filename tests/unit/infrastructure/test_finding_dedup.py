"""Missing id columns and invalid geometries produce one finding per root cause."""

import geopandas as gpd  # type: ignore[import-untyped]
from shapely.geometry import Point, Polygon

import geoqc
from geoqc.domain.rules import Severity


def test_missing_id_column_becomes_critical_finding_with_row_index_ids() -> None:
    frame = gpd.GeoDataFrame({"value": [1, 1]}, geometry=[Point(1, 2), Point(1, 2)])
    profile = geoqc.QualityProfile("ids", id_column="parcel_id", require_crs=False)

    result = geoqc.audit_geodataframe(frame, profile=profile)

    missing = [issue for issue in result.issues if issue.metadata.get("column") == "parcel_id"]
    assert len(missing) == 1
    assert missing[0].severity is Severity.CRITICAL
    assert all(
        issue.feature_id == issue.feature_index
        for issue in result.issues
        if issue.feature_index is not None
    )


def test_self_intersecting_polygon_reports_only_the_specific_issue() -> None:
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    frame = gpd.GeoDataFrame(geometry=[bowtie], crs="EPSG:32748")
    profile = geoqc.QualityProfile(
        "parcels",
        preset=geoqc.QualityPreset.PARCEL,
        minimum_area=5.0,
    )

    result = geoqc.audit_geodataframe(frame, profile=profile)

    assert [issue.code for issue in result.issues] == ["GEO-SELF_INTERSECTION"]
