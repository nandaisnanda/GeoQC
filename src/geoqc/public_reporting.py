"""Public conversion from audit results to renderer-ready reports."""

from collections.abc import Callable

import shapely
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError

from geoqc.domain.models import DatasetAuditResult
from geoqc.domain.models.quality_report import (
    GeographicPoint,
    QualityReport,
    QualityReportIssue,
)


def _map_locator(crs: str | None) -> Callable[[str], GeographicPoint | None]:
    """Return a function that places an issue WKT on the WGS84 report map."""
    if crs is None:
        return lambda _: None
    try:
        transformer = Transformer.from_crs(CRS.from_user_input(crs), "EPSG:4326", always_xy=True)
    except CRSError:
        return lambda _: None

    def locate(wkt: str) -> GeographicPoint | None:
        try:
            geometry = shapely.from_wkt(wkt)
            if geometry is None or geometry.is_empty:
                return None
            point = geometry.representative_point()
            longitude, latitude = transformer.transform(point.x, point.y)
            return GeographicPoint(latitude=latitude, longitude=longitude)
        except (shapely.errors.GEOSException, ValueError):
            # Invalid geometry or coordinates outside the CRS area stay off the map.
            return None

    return locate


def build_quality_report(result: DatasetAuditResult) -> QualityReport:
    """Convert a dataset audit into the existing renderer-ready report model."""
    locate = _map_locator(result.crs_guard.crs)
    issues = tuple(
        QualityReportIssue(
            code=item.code,
            title=item.title,
            description=item.message,
            severity=item.severity,
            category=item.category.title(),
            recommendation=item.recommendation,
            location=(
                f"{item.layer or result.dataset_name}, feature {item.feature_index}"
                if item.feature_index is not None
                else item.layer or result.dataset_name
            ),
            map_location=locate(item.geometry_wkt),
        )
        for item in result.issues
    )
    return QualityReport(
        title="GeoQC dataset quality report",
        dataset_name=result.dataset_name,
        total_checks=max(1, result.feature_count),
        passed_checks=max(
            0,
            result.feature_count
            - len({item.feature_index for item in result.issues if item.feature_index is not None}),
        ),
        issues=issues,
        summary=(
            f"Quality score {result.quality_score:.2f}/100; "
            f"{len(result.issues)} issue(s) found across {result.feature_count} feature(s)."
        ),
    )
