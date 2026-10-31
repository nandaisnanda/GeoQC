from pathlib import Path

import pytest
from typer.testing import CliRunner

from geoqc.interfaces.cli.main import app

ROOT = Path(__file__).resolve().parents[3]


def _check(*args: str) -> str:
    with pytest.warns(DeprecationWarning):
        result = CliRunner().invoke(app, ["check", *args, "--no-output"])
    return result.stdout


def test_jalan_preset_binds_to_shapefile_layer() -> None:
    stdout = _check(str(ROOT / "testdata" / "jalanlokal.shp"), "--preset", "jalan")

    assert "Preset jalan applied to layer jalanlokal" in stdout
    assert "TOP-NO-DANGLES" in stdout
    assert "Warning: no topology rule" not in stdout


def test_bidang_tanah_preset_binds_to_selected_layer() -> None:
    stdout = _check(
        str(ROOT / "examples" / "sample_defects.gpkg"),
        "--layer",
        "parcels",
        "--preset",
        "bidang-tanah",
    )

    assert "Preset bidang-tanah applied to layer parcels" in stdout
    assert "TOP-NO-OVERLAP" in stdout
    assert "Warning: no topology rule" not in stdout


def test_cross_layer_preset_keeps_names_and_warns() -> None:
    stdout = _check(
        str(ROOT / "examples" / "sample_defects.gpkg"),
        "--layer",
        "parcels",
        "--preset",
        "konsesi-kawasan-hutan",
    )

    assert "applied to layer" not in stdout
    assert "Warning: no topology rule applies to 'parcels'" in stdout
