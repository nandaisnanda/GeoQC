"""Map locations in build_quality_report for located, CRS-less and unplaceable issues."""

from dataclasses import replace

import pytest
from shapely.geometry import Point, box

import geoqc
from geoqc.domain.models import DatasetAuditResult
from geoqc.public_reporting import _map_locator

# Two overlapping parcels near Yogyakarta, in UTM zone 49S metres.
_PARCELS = [box(440000, 9140000, 440100, 9140100), box(440050, 9140050, 440150, 9140150)]


def _overlap_audit(crs: str | None) -> DatasetAuditResult:
    return geoqc.audit_geometries(_PARCELS, preset="parcel", crs=crs)


def test_projected_issue_is_placed_on_the_wgs84_map() -> None:
    report = geoqc.build_quality_report(_overlap_audit("EPSG:32749"))

    located = [issue.map_location for issue in report.issues if issue.map_location]
    assert located
    for point in located:
        assert -8.0 < point.latitude < -7.5
        assert 110.0 < point.longitude < 110.8


def test_dataset_without_crs_keeps_issues_but_places_none_on_the_map() -> None:
    audit = _overlap_audit(None)
    assert audit.issues

    report = geoqc.build_quality_report(audit)

    assert len(report.issues) == len(audit.issues)
    assert all(issue.map_location is None for issue in report.issues)


def test_unparseable_crs_places_none_on_the_map() -> None:
    audit = _overlap_audit("EPSG:32749")
    broken = replace(audit, crs_guard=replace(audit.crs_guard, crs="not-a-crs"))

    report = geoqc.build_quality_report(broken)

    assert len(report.issues) == len(audit.issues)
    assert all(issue.map_location is None for issue in report.issues)


def test_empty_geometry_is_left_off_the_map() -> None:
    audit = geoqc.audit_geometries([Point()], crs="EPSG:4326")

    report = geoqc.build_quality_report(audit)

    assert report.issues[0].code == "GEO-EMPTY_GEOMETRY"
    assert report.issues[0].map_location is None


def test_unreadable_geometry_text_is_left_off_the_map() -> None:
    audit = _overlap_audit("EPSG:32749")
    damaged = replace(
        audit, issues=tuple(replace(issue, geometry_wkt="NOT A GEOMETRY") for issue in audit.issues)
    )

    report = geoqc.build_quality_report(damaged)

    assert len(report.issues) == len(audit.issues)
    assert all(issue.map_location is None for issue in report.issues)


@pytest.mark.parametrize("crs", [None, "not-a-crs"])
def test_locator_without_a_usable_crs_returns_none_for_any_input(crs: str | None) -> None:
    locate = _map_locator(crs)

    assert locate("POINT (1 2)") is None
    assert locate("POINT EMPTY") is None
