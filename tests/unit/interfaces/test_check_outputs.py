"""`geoqc check` writes a report and an issue GeoPackage next to the input."""

from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import pyogrio  # type: ignore[import-untyped]
import pytest
from shapely.geometry import Point, box
from typer.testing import CliRunner, Result

from geoqc import audit_dataset, build_quality_report
from geoqc.interfaces.cli import main
from geoqc.interfaces.cli.main import app

# Two overlapping 10 m parcels in UTM zone 49S, near Yogyakarta.
_PARCELS = [
    box(430_000, 9_120_000, 430_010, 9_120_010),
    box(430_005, 9_120_005, 430_015, 9_120_015),
]


def _write_parcels(source: Path) -> None:
    gpd.GeoDataFrame(geometry=_PARCELS, crs="EPSG:32749").to_file(source)


def _check(*args: str) -> Result:
    with pytest.warns(DeprecationWarning):
        return CliRunner().invoke(app, ["check", *args])


def _issue_rows(gpkg: Path) -> int:
    return sum(len(gpd.read_file(gpkg, layer=name)) for name, _ in pyogrio.list_layers(gpkg))


def test_check_writes_report_and_issue_gpkg_next_to_input(tmp_path: Path) -> None:
    source = tmp_path / "parcels.shp"
    _write_parcels(source)

    result = _check(str(source))

    issues = tmp_path / "parcels_issues.gpkg"
    report = tmp_path / "parcels_report.html"
    assert f"Issue layers: {issues.resolve()}" in result.stdout
    assert f"Report: {report.resolve()}" in result.stdout
    assert _issue_rows(issues) == int(result.stdout.split("issues=")[1].split()[0]) > 0
    assert "leaflet" in report.read_text(encoding="utf-8").casefold()


def test_check_overwrites_default_outputs_on_rerun(tmp_path: Path) -> None:
    source = tmp_path / "parcels.shp"
    _write_parcels(source)
    _check(str(source))

    result = _check(str(source))

    assert result.exit_code != 2, result.output
    assert (tmp_path / "parcels_issues.gpkg").exists()


def test_no_output_writes_nothing(tmp_path: Path) -> None:
    source = tmp_path / "parcels.shp"
    _write_parcels(source)

    result = _check(str(source), "--no-output")

    assert "Issue layers:" not in result.stdout
    assert not (tmp_path / "parcels_issues.gpkg").exists()
    assert not (tmp_path / "parcels_report.html").exists()


def test_explicit_paths_replace_the_defaults(tmp_path: Path) -> None:
    source = tmp_path / "parcels.shp"
    issues = tmp_path / "out" / "custom.gpkg"
    report = tmp_path / "out" / "custom.json"
    _write_parcels(source)

    _check(str(source), "--issues", str(issues), "--report", str(report))

    assert issues.exists()
    assert report.exists()
    assert not (tmp_path / "parcels_issues.gpkg").exists()
    assert not (tmp_path / "parcels_report.html").exists()


def test_explicit_report_still_written_with_no_output(tmp_path: Path) -> None:
    source = tmp_path / "parcels.shp"
    report = tmp_path / "custom.html"
    _write_parcels(source)

    _check(str(source), "--no-output", "--report", str(report))

    assert report.exists()
    assert not (tmp_path / "parcels_issues.gpkg").exists()


def test_missing_report_extra_skips_html_with_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing_extra(*_: object, **__: object) -> Path:
        raise ModuleNotFoundError("No module named 'folium'", name="folium")

    monkeypatch.setattr(main, "write_audit_report", missing_extra)
    source = tmp_path / "parcels.shp"
    _write_parcels(source)

    result = _check(str(source))

    assert result.exit_code != 2, result.output
    assert 'pip install "geoqc[report]"' in result.stdout
    assert "Report:" not in result.stdout
    assert (tmp_path / "parcels_issues.gpkg").exists()


def test_multi_layer_gpkg_writes_outputs_per_layer(tmp_path: Path) -> None:
    source = tmp_path / "multi.gpkg"
    gpd.GeoDataFrame(geometry=_PARCELS, crs="EPSG:32749").to_file(source, layer="parcels")
    gpd.GeoDataFrame(geometry=[Point(430_000, 9_120_000)], crs="EPSG:32749").to_file(
        source, layer="wells"
    )

    _check(str(source))

    for name in ("parcels", "wells"):
        assert (tmp_path / f"multi_{name}_issues.gpkg").exists()
        assert (tmp_path / f"multi_{name}_report.html").exists()


def test_report_places_issues_on_wgs84_map(tmp_path: Path) -> None:
    source = tmp_path / "parcels.gpkg"
    _write_parcels(source)

    report = build_quality_report(audit_dataset(source, profile="parcel"))

    [location] = {issue.map_location for issue in report.issues if issue.code == "TOP-NO-OVERLAP"}
    assert location is not None
    assert -8.0 < location.latitude < -7.8
    assert 110.3 < location.longitude < 110.4


def test_report_without_crs_has_no_map_locations(tmp_path: Path) -> None:
    source = tmp_path / "parcels.gpkg"
    gpd.GeoDataFrame(geometry=_PARCELS).to_file(source)

    report = build_quality_report(audit_dataset(source, profile="parcel"))

    assert report.issues
    assert all(issue.map_location is None for issue in report.issues)
