from __future__ import annotations

from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
from typer.testing import CliRunner

from geoqc.interfaces.cli.main import app

SAMPLE_DEFECTS = Path(__file__).parents[3] / "examples" / "sample_defects.gpkg"


def test_invalid_before_has_null_area_change_and_note(tmp_path: Path) -> None:
    output = tmp_path / "out.gpkg"

    args = ["fix", str(SAMPLE_DEFECTS), str(output), "--layer", "parcels"]
    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    log = gpd.read_file(output, layer="geoqc_fix_log").set_index("feature_index")
    assert log.loc[1, "area_before"] == 0
    assert log.loc[1, "area_after"] == 800
    assert log["area_change_pct"].isna()[1]
    assert log.loc[1, "area_note"] == "before invalid, area not comparable"
    valid = log.drop(index=1)
    assert valid["area_note"].isna().all()
    assert valid["area_change_pct"].notna().all()
