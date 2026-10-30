"""Generic profiles: no road checks on unknown lines, sliver warnings on unknown polygons."""

from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import pytest
from shapely.geometry import LineString, box
from typer.testing import CliRunner

from geoqc import audit_dataset
from geoqc.interfaces.cli.main import app

_REPO = Path(__file__).resolve().parents[3]
_HINT = "Road network checks off; use --preset jalan for roads."


def _issue_codes(source: Path, layer: str | None = None) -> list[str]:
    with pytest.warns(DeprecationWarning):
        result = CliRunner().invoke(
            app, ["check", str(source), "--no-output", *(["--layer", layer] if layer else [])]
        )
    assert result.exit_code == 0, result.output
    return [result.stdout]


def test_generic_line_skips_road_checks_and_prints_hint(tmp_path: Path) -> None:
    source = tmp_path / "river.geojson"
    # A dangling end on a lone line is a ROAD-DEAD_END under the road preset.
    gpd.GeoDataFrame(
        geometry=[LineString([(0, 0), (100, 0)]), LineString([(100, 0), (200, 50)])],
        crs="EPSG:32749",
    ).to_file(source, driver="GeoJSON")

    (stdout,) = _issue_codes(source)

    assert _HINT in stdout
    assert "issues=0" in stdout


def test_jalanlokal_has_no_road_findings() -> None:
    from geoqc.infrastructure.gis.profile_loading import _generic_profile
    from geoqc.interfaces.cli.main import _auto_profile

    profile = _auto_profile(_REPO / "testdata" / "jalanlokal.shp", None)
    result = audit_dataset(_REPO / "testdata" / "jalanlokal.shp", profile=profile)

    assert _generic_profile("LineString") is not None
    assert not [issue for issue in result.issues if issue.code.startswith("ROAD-")]


def test_explicit_road_preset_keeps_road_checks() -> None:
    with pytest.warns(DeprecationWarning):
        result = CliRunner().invoke(
            app,
            [
                "check",
                str(_REPO / "testdata" / "jalanlokal.shp"),
                "--preset",
                "road",
                "--no-output",
            ],
        )

    assert _HINT not in result.stdout


def test_generic_polygon_flags_sample_sliver() -> None:
    sample = _REPO / "examples" / "sample_defects.gpkg"
    with pytest.warns(DeprecationWarning):
        result = CliRunner().invoke(
            app, ["check", str(sample), "--layer", "parcels", "--no-output"]
        )

    assert "Preset: generic-polygon" in result.stdout
    assert "issues=3" in result.stdout


def test_generic_polygon_sliver_findings_are_warnings(tmp_path: Path) -> None:
    from geoqc import audit_dataset as run
    from geoqc.domain.rules import Severity
    from geoqc.infrastructure.gis.profile_loading import _generic_profile

    source = tmp_path / "p.geojson"
    gpd.GeoDataFrame(
        geometry=[box(0, 0, 10, 10), box(20, 0, 20.5, 1), box(30, 0, 130, 0.05)], crs="EPSG:32749"
    ).to_file(source, driver="GeoJSON")

    result = run(source, profile=_generic_profile("Polygon"))

    slivers = [issue for issue in result.issues if issue.code == "TOP-SLIVER"]
    assert sorted(issue.feature_index for issue in slivers) == [1, 2]
    assert {issue.severity for issue in slivers} == {Severity.WARNING}


def test_generic_polygon_sliver_uses_utm_for_geographic_crs(tmp_path: Path) -> None:
    from geoqc.infrastructure.gis.profile_loading import _generic_profile

    source = tmp_path / "geo.geojson"
    # About 0.5 m x 0.5 m near Jakarta (1e-5 degrees is roughly 1.1 m).
    gpd.GeoDataFrame(
        geometry=[box(106.8, -6.2, 106.800005, -6.199995), box(106.81, -6.2, 106.82, -6.19)],
        crs="EPSG:4326",
    ).to_file(source, driver="GeoJSON")

    result = audit_dataset(source, profile=_generic_profile("Polygon"))

    assert [i.feature_index for i in result.issues if i.code == "TOP-SLIVER"] == [0]


def test_generic_polygon_sliver_skipped_without_crs(tmp_path: Path) -> None:
    from geoqc.infrastructure.gis.profile_loading import _generic_profile

    source = tmp_path / "nocrs.geojson"
    source.write_text(
        '{"type":"FeatureCollection","crs":null,"features":[{"type":"Feature","properties":{},'
        '"geometry":{"type":"Polygon","coordinates":[[[0,0],[0.5,0],[0.5,0.5],[0,0.5],[0,0]]]}}]}'
    )

    result = audit_dataset(source, profile=_generic_profile("Polygon"))

    assert not [i for i in result.issues if i.code == "TOP-SLIVER"]
