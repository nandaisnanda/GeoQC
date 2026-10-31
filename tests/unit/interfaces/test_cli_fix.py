from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
from shapely.geometry import LineString, Polygon
from typer.testing import CliRunner

from geoqc.interfaces.cli.main import app

runner = CliRunner()
SAMPLE_DEFECTS = Path(__file__).parents[3] / "examples" / "sample_defects.gpkg"
LOG_COLUMNS = [
    "layer",
    "feature_index",
    "actions",
    "area_before",
    "area_after",
    "area_change_pct",
    "area_note",
    "max_shift",
    "review_reason",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _line_source(tmp_path: Path) -> Path:
    bowtie = LineString([(0, 0), (2, 2), (2, 0), (0, 2)])
    clean = LineString([(5, 0), (6, 1)])
    source = tmp_path / "lines.gpkg"
    gpd.GeoDataFrame(geometry=[clean, bowtie], crs="EPSG:32749").to_file(
        source, layer="lines", driver="GPKG"
    )
    return source


def test_fix_flags_self_intersecting_line_and_keeps_geometry(tmp_path: Path) -> None:
    source = _line_source(tmp_path)
    output = tmp_path / "out.gpkg"

    result = runner.invoke(app, ["fix", str(source), str(output)])

    assert result.exit_code == 0, result.output
    assert "Fixed 0, needs review 1" in result.stdout
    fixed = gpd.read_file(output, layer="lines")
    original = gpd.read_file(source, layer="lines")
    assert fixed["geoqc_review"].isna().tolist() == [True, False]
    assert fixed["geoqc_review"].iloc[1] == "self_intersection"
    assert fixed.geometry.equals(original.geometry)


def test_fix_processes_every_layer_when_layer_is_omitted(tmp_path: Path) -> None:
    output = tmp_path / "all.gpkg"

    result = runner.invoke(app, ["fix", str(SAMPLE_DEFECTS), str(output)])

    assert result.exit_code == 0, result.output
    assert "layer=parcels Fixed 1, needs review 1" in result.stdout
    assert "layer=roads Fixed 0, needs review 0" in result.stdout
    assert len(gpd.read_file(output, layer="parcels")) == len(
        gpd.read_file(SAMPLE_DEFECTS, layer="parcels")
    )
    assert len(gpd.read_file(output, layer="roads")) > 0


def test_fix_log_layer_has_expected_columns(tmp_path: Path) -> None:
    output = tmp_path / "all.gpkg"
    runner.invoke(app, ["fix", str(SAMPLE_DEFECTS), str(output)])

    log = gpd.read_file(output, layer="geoqc_fix_log")

    assert list(log.columns) == [*LOG_COLUMNS]
    assert set(log["layer"]) == {"parcels"}
    assert sorted(log["feature_index"]) == [1, 3]
    assert log["review_reason"].tolist().count("overlap") == 1


def test_fix_log_covers_flagged_line(tmp_path: Path) -> None:
    source = _line_source(tmp_path)
    output = tmp_path / "out.gpkg"
    runner.invoke(app, ["fix", str(source), str(output)])

    log = gpd.read_file(output, layer="geoqc_fix_log")

    assert log["feature_index"].tolist() == [1]
    assert log["review_reason"].tolist() == ["self_intersection"]
    assert log["max_shift"].tolist() == [0.0]


def test_fix_reports_area_change_for_repaired_polygon(tmp_path: Path) -> None:
    bowtie = Polygon([(0, 0), (4, 4), (4, 0), (0, 4)])
    source = tmp_path / "poly.gpkg"
    gpd.GeoDataFrame(geometry=[bowtie], crs="EPSG:32749").to_file(
        source, layer="poly", driver="GPKG"
    )
    output = tmp_path / "out.gpkg"

    result = runner.invoke(app, ["fix", str(source), str(output), "--layer", "poly"])

    assert result.exit_code == 0, result.output
    log = gpd.read_file(output, layer="geoqc_fix_log")
    assert log["actions"].tolist() == ["self_intersection"]
    assert log["area_after"].iloc[0] > log["area_before"].iloc[0]


def test_fix_leaves_input_hash_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "sample.gpkg"
    shutil.copyfile(SAMPLE_DEFECTS, source)
    before = _sha256(source)

    result = runner.invoke(app, ["fix", str(source), str(tmp_path / "out.gpkg")])

    assert result.exit_code == 0, result.output
    assert _sha256(source) == before
