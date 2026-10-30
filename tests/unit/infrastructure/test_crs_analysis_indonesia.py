"""Tests for Indonesian CRS recognition and missing-CRS guesses."""

from pathlib import Path

import geopandas as gpd
from pyproj import CRS
from shapely.geometry import Point, box

import geoqc
from geoqc.infrastructure.gis.crs_analysis import assess_crs


def test_epsg_32749_is_recognized_as_utm_49s() -> None:
    result = assess_crs("EPSG:32749")

    assert result.status is geoqc.CrsUnitStatus.SAFE
    assert "WGS 84 / UTM zone 49S" in result.message


def test_srgi2013_and_tm3_are_recognized_by_name() -> None:
    srgi = CRS.from_user_input("SRGI2013").to_wkt()
    tm3 = CRS.from_user_input("DGN95 / Indonesia TM-3 zone 49.1").to_wkt()

    assert "Recognized Indonesian CRS: SRGI2013" in assess_crs(srgi).message
    assert "DGN95 / Indonesia TM-3 zone 49.1" in assess_crs(tm3).message


def test_non_indonesian_crs_is_not_labelled() -> None:
    assert "Indonesian" not in assess_crs("EPSG:32631").message


def test_missing_crs_with_degree_ranges_suggests_crs_without_assigning() -> None:
    result = assess_crs(None, [Point(110.4, -7.8), Point(110.5, -7.7)])

    assert result.crs is None
    assert result.status is geoqc.CrsUnitStatus.UNKNOWN
    assert (
        result.suggested_projected_crs == CRS.from_user_input("WGS 84 / UTM zone 49S").to_string()
    )
    assert "probably geographic" in result.message
    assert "not assigned" in result.message


def test_missing_crs_with_metre_ranges_reports_unknown_zone() -> None:
    result = assess_crs(None, [box(430_000, 9_130_000, 431_000, 9_131_000)])

    assert result.crs is None
    assert result.suggested_projected_crs is None
    assert "zone is unknown" in result.message


def test_missing_crs_outside_indonesia_adds_no_guess() -> None:
    result = assess_crs(None, [Point(5, 50)])

    assert result.suggested_projected_crs is None
    assert "Indonesia" not in result.message


def test_shapefile_without_prj_gets_crs_suggestion(tmp_path: Path) -> None:
    path = tmp_path / "parcels.shp"
    gpd.GeoDataFrame(
        {"id": [1, 2]},
        geometry=[box(110.40, -7.80, 110.41, -7.79), box(110.42, -7.80, 110.43, -7.79)],
        crs="EPSG:4326",
    ).to_file(path)
    path.with_suffix(".prj").unlink()

    result = geoqc.audit_dataset(path)

    assert result.crs_guard.crs is None
    assert result.crs_guard.suggested_projected_crs == "EPSG:32749"
    assert "WGS 84" in result.crs_guard.message
