"""`geoqc check` without --preset picks a generic preset from the geometry type."""

from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import pytest
from shapely.geometry import LineString, Point, box
from typer.testing import CliRunner

from geoqc.domain.models import QualityPreset
from geoqc.infrastructure.gis.profile_loading import _generic_profile
from geoqc.interfaces.cli.main import app

_REPO = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("geometry_type", "name", "preset"),
    [
        ("Polygon", "generic-polygon", QualityPreset.PARCEL),
        ("MultiPolygon Z", "generic-polygon", QualityPreset.PARCEL),
        ("LineString Z", "generic-line", QualityPreset.ROAD),
        ("MultiLineString", "generic-line", QualityPreset.ROAD),
        ("Point", "generic-point", QualityPreset.POINT_SURVEY),
        ("MultiPoint", "generic-point", QualityPreset.POINT_SURVEY),
    ],
)
def test_generic_profile_matches_geometry_type(
    geometry_type: str, name: str, preset: QualityPreset
) -> None:
    profile = _generic_profile(geometry_type)

    assert profile is not None
    assert profile.name == name
    assert profile.preset is preset
    assert profile.attribute_rules == ()
    assert profile.id_column is None
    assert not profile.require_crs


@pytest.mark.parametrize("geometry_type", [None, "Unknown", "GeometryCollection"])
def test_generic_profile_is_none_for_mixed_or_unknown_types(geometry_type: str | None) -> None:
    assert _generic_profile(geometry_type) is None


@pytest.mark.parametrize(
    ("geometry", "expected"),
    [
        (box(0, 0, 1, 1), "Preset: generic-polygon"),
        (LineString([(0, 0), (1, 1)]), "Preset: generic-line"),
        (Point(1, 2), "Preset: generic-point"),
    ],
)
def test_check_without_preset_prints_the_chosen_preset(
    tmp_path: Path, geometry: object, expected: str
) -> None:
    source = tmp_path / "data.geojson"
    gpd.GeoDataFrame(geometry=[geometry], crs="EPSG:32749").to_file(source, driver="GeoJSON")

    with pytest.warns(DeprecationWarning):
        result = CliRunner().invoke(app, ["check", str(source)])

    assert result.exit_code == 0, result.output
    assert expected in result.stdout
    assert "PASS" in result.stdout


def test_check_without_preset_picks_per_layer_in_a_geopackage(tmp_path: Path) -> None:
    source = tmp_path / "multi.gpkg"
    gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1)], crs="EPSG:32749").to_file(source, layer="a")
    gpd.GeoDataFrame(geometry=[Point(1, 2)], crs="EPSG:32749").to_file(source, layer="b")

    with pytest.warns(DeprecationWarning):
        result = CliRunner().invoke(app, ["check", str(source)])

    assert "Preset: generic-polygon" in result.stdout
    assert "Preset: generic-point" in result.stdout


def test_explicit_preset_skips_auto_selection(tmp_path: Path) -> None:
    source = tmp_path / "points.geojson"
    gpd.GeoDataFrame(geometry=[Point(1, 2)], crs="EPSG:4326").to_file(source, driver="GeoJSON")

    with pytest.warns(DeprecationWarning):
        result = CliRunner().invoke(app, ["check", str(source), "--preset", "point_survey"])

    assert "Preset:" not in result.stdout


def test_check_picks_preset_for_sample_road_shapefile() -> None:
    source = _REPO / "testdata" / "jalanarteri.shp"

    with pytest.warns(DeprecationWarning):
        result = CliRunner().invoke(app, ["check", str(source), "--no-output"])

    assert result.exit_code == 0, result.output
    assert "Preset: generic-line (geometry type LineString Z in jalanarteri.shp)" in result.stdout
