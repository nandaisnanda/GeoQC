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


def test_check_writes_report_and_issue_gpkg_in_geoqc_output(tmp_path: Path) -> None:
    source = tmp_path / "parcels.shp"
    _write_parcels(source)

    result = _check(str(source))

    issues = tmp_path / "geoqc_output" / "parcels_issues.gpkg"
    report = tmp_path / "geoqc_output" / "parcels_report.html"
    assert f"Issue layers: {issues.resolve()}" in result.stdout
    assert f"Report: {report.resolve()}" in result.stdout
    assert _issue_rows(issues) > 0
    assert "leaflet" in report.read_text(encoding="utf-8").casefold()


def test_check_overwrites_default_outputs_on_rerun(tmp_path: Path) -> None:
    source = tmp_path / "parcels.shp"
    _write_parcels(source)
    _check(str(source))

    result = _check(str(source))

    assert result.exit_code != 2, result.output
    assert (tmp_path / "geoqc_output" / "parcels_issues.gpkg").exists()


def test_no_output_writes_nothing(tmp_path: Path) -> None:
    source = tmp_path / "parcels.shp"
    _write_parcels(source)

    result = _check(str(source), "--no-output")

    assert "Issue layers:" not in result.stdout
    assert not (tmp_path / "geoqc_output" / "parcels_issues.gpkg").exists()
    assert not (tmp_path / "geoqc_output" / "parcels_report.html").exists()


def test_explicit_paths_replace_the_defaults(tmp_path: Path) -> None:
    source = tmp_path / "parcels.shp"
    issues = tmp_path / "out" / "custom.gpkg"
    report = tmp_path / "out" / "custom.json"
    _write_parcels(source)

    _check(str(source), "--issues", str(issues), "--report", str(report))

    assert issues.exists()
    assert report.exists()
    assert not (tmp_path / "geoqc_output" / "parcels_issues.gpkg").exists()
    assert not (tmp_path / "geoqc_output" / "parcels_report.html").exists()


def test_explicit_report_still_written_with_no_output(tmp_path: Path) -> None:
    source = tmp_path / "parcels.shp"
    report = tmp_path / "custom.html"
    _write_parcels(source)

    _check(str(source), "--no-output", "--report", str(report))

    assert report.exists()
    assert not (tmp_path / "geoqc_output" / "parcels_issues.gpkg").exists()


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
    assert (tmp_path / "geoqc_output" / "parcels_issues.gpkg").exists()


def test_multi_layer_gpkg_writes_outputs_per_layer(tmp_path: Path) -> None:
    source = tmp_path / "multi.gpkg"
    gpd.GeoDataFrame(geometry=_PARCELS, crs="EPSG:32749").to_file(source, layer="parcels")
    gpd.GeoDataFrame(geometry=[Point(430_000, 9_120_000)], crs="EPSG:32749").to_file(
        source, layer="wells"
    )

    _check(str(source))

    for name in ("parcels", "wells"):
        assert (tmp_path / "geoqc_output" / f"multi_{name}_issues.gpkg").exists()
        assert (tmp_path / "geoqc_output" / f"multi_{name}_report.html").exists()


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


_NAMES = {"batas-administrasi", "bidang-tanah", "kawasan-hutan", "jalan", "konsesi-kawasan-hutan"}


def test_presets_command_lists_packaged_and_generic_presets() -> None:
    result = CliRunner().invoke(app, ["presets"])

    assert result.exit_code == 0, result.output
    for name in (*_NAMES, "parcel", "road"):
        assert name in result.stdout
    assert "Bidang tanah" in result.stdout


def test_presets_command_groups_output_with_own_descriptions() -> None:
    result = CliRunner().invoke(app, ["presets"])

    out = result.stdout
    assert "Generic preset by geometry type." not in out
    indonesian = out.index("Indonesian presets:")
    general = out.index("General presets:")
    automatic = out.index("Automatic (used when no preset is given):")
    assert indonesian < general < automatic
    position = {
        line.split()[0]: out.index(line) for line in out.splitlines() if line.startswith("  ")
    }
    assert indonesian < position["jalan"] < general
    for name in ("parcel", "road", "admin_boundary", "point_survey"):
        assert general < position[name] < automatic
    for name in ("generic-polygon", "generic-line", "generic-point"):
        assert position[name] > automatic


def test_packaged_presets_match_docs_examples_and_load() -> None:
    from geoqc.infrastructure.gis.profile_loading import (
        list_builtin_presets,
        load_builtin_preset,
    )

    assert set(list_builtin_presets()) == _NAMES
    for name in _NAMES:
        assert load_builtin_preset(name).name == name
        packaged = (Path(main.__file__).parents[2] / "presets" / f"{name}.yaml").read_bytes()
        assert packaged == (Path("docs/examples") / f"{name}.yaml").read_bytes()


def test_check_accepts_indonesian_preset_name(tmp_path: Path) -> None:
    source = tmp_path / "bidang_tanah.gpkg"
    _write_parcels(source)

    result = _check(str(source), "--preset", "bidang-tanah", "--no-output")

    assert result.exit_code != 2, result.output
    assert "QC complete" not in result.stdout
    assert result.stdout.startswith(("PASS", "FAIL"))


def test_check_still_accepts_generic_preset_and_rejects_unknown(tmp_path: Path) -> None:
    source = tmp_path / "parcels.shp"
    _write_parcels(source)

    generic = _check(str(source), "--preset", "parcel", "--no-output")
    unknown = _check(str(source), "--preset", "nope", "--no-output")

    assert generic.exit_code != 2, generic.output
    assert unknown.exit_code == 2
    assert "bidang-tanah" in unknown.output


def test_preset_warns_when_its_layer_does_not_match_the_dataset(tmp_path: Path) -> None:
    mismatched = tmp_path / "parcels.shp"
    matching = tmp_path / "bidang_tanah.gpkg"
    _write_parcels(mismatched)
    _write_parcels(matching)

    other = _check(str(mismatched), "--preset", "bidang-tanah", "--no-output")
    same = _check(str(matching), "--preset", "bidang-tanah", "--no-output")

    assert "Preset bidang-tanah applied to layer parcels" in other.stdout
    assert "Warning: no topology rule" not in other.stdout
    assert "Warning: no topology rule" not in same.stdout


def test_preset_descriptions_stay_on_one_short_line() -> None:
    from geoqc.infrastructure.gis.profile_loading import list_builtin_presets

    assert all(len(text) <= 80 for text in list_builtin_presets().values())
