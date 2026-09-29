"""CLI contract for the unified quality workflow."""

import json
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
from shapely.geometry import Point
from typer.testing import CliRunner

from geoqc.interfaces.cli.main import app


def test_check_command_writes_outputs_and_returns_gate_failure(tmp_path: Path) -> None:
    source = tmp_path / "points.geojson"
    issues = tmp_path / "issues.gpkg"
    report = tmp_path / "report.json"
    gpd.GeoDataFrame(geometry=[Point(1, 2), Point(1, 2)], crs="EPSG:4326").to_file(
        source, driver="GeoJSON"
    )

    result = CliRunner().invoke(
        app,
        [
            "check",
            str(source),
            "--preset",
            "point_survey",
            "--issues",
            str(issues),
            "--report",
            str(report),
            "--fail-on",
            "warning",
        ],
    )

    assert result.exit_code == 1
    assert "status=FAIL" in result.stdout
    assert issues.exists()
    assert json.loads(report.read_text(encoding="utf-8"))["schema_version"] == "1.0"


def test_check_command_accepts_yaml_profile_and_passes_clean_data(tmp_path: Path) -> None:
    source = tmp_path / "points.geojson"
    profile = tmp_path / "profile.yaml"
    gpd.GeoDataFrame(geometry=[Point(1, 2)], crs="EPSG:4326").to_file(source, driver="GeoJSON")
    profile.write_text(
        """name: survey
version: 1
preset: point_survey
crs:
  required: true
quality_gate:
  minimum_score: 100
  fail_on: error
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["check", str(source), "--profile", str(profile)])

    assert result.exit_code == 0
    assert "status=PASS" in result.stdout
