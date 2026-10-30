"""`geoqc check` explains PASS and FAIL: severity counts, score, top issue codes."""

import re
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
from shapely.geometry import Point
from typer.testing import CliRunner

from geoqc.interfaces.cli.main import app

_REPO = Path(__file__).resolve().parents[3]


def test_fail_verdict_lists_severities_score_and_top_codes() -> None:
    sample = _REPO / "examples" / "sample_defects.gpkg"

    result = CliRunner().invoke(app, ["check", str(sample), "--layer", "parcels", "--no-output"])

    lines = result.stdout.splitlines()
    verdict = next(line for line in lines if line.startswith("FAIL:"))
    assert re.fullmatch(r"FAIL: 2 errors, 1 warning \(score \d+/100\)", verdict)
    codes = lines[lines.index(verdict) + 1 :]
    assert codes[0].startswith("  ") and re.fullmatch(r"  [A-Z]+-[A-Z_]+ x\d+", codes[0])
    assert len([line for line in codes if re.fullmatch(r"  \S+ x\d+", line)]) == 3


def test_pass_verdict_has_score_only(tmp_path: Path) -> None:
    source = tmp_path / "points.geojson"
    gpd.GeoDataFrame(geometry=[Point(1, 2)], crs="EPSG:32749").to_file(source, driver="GeoJSON")

    result = CliRunner().invoke(app, ["check", str(source), "--no-output"])

    assert "PASS (score 100/100)" in result.stdout
    assert "FAIL" not in result.stdout
