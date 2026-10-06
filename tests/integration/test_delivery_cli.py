"""End-to-end delivery command contracts with real small geospatial datasets."""

import json
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import pytest
from shapely.geometry import Point
from typer.testing import CliRunner

from geoqc.application.services import (
    AxisOrderDetector,
    CrsConsistencyScanner,
    DatumShiftDetector,
)
from geoqc.domain.models import DatumShiftSample, DatumTransformationEvidence
from geoqc.infrastructure.gis.pyproj_datum_inspector import PyprojDatumTransformationInspector
from geoqc.infrastructure.reporting import HtmlReportRenderer
from geoqc.interfaces.cli import delivery
from geoqc.interfaces.cli.main import app

RUNNER = CliRunner()


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    path = tmp_path / "points.gpkg"
    gpd.GeoDataFrame(geometry=[Point(110, -7)], crs="EPSG:4326").to_file(path)
    return path


@pytest.mark.parametrize("command", ["crs-scan", "batch"])
def test_file_commands_are_successful_and_deterministic(command: str, dataset: Path) -> None:
    args = [command, str(dataset), "--json"]
    first = RUNNER.invoke(app, args)
    second = RUNNER.invoke(app, args)
    assert first.exit_code == second.exit_code == 0, first.output
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)
    human = RUNNER.invoke(app, [command, str(dataset)])
    assert human.exit_code == 0
    assert human.stdout


@pytest.mark.parametrize("command", ["crs-scan", "batch", "html-report"])
@pytest.mark.parametrize("kind", ["missing", "malformed"])
def test_invalid_files(command: str, kind: str, tmp_path: Path) -> None:
    path = tmp_path / "bad.gpkg"
    if kind == "malformed":
        path.write_bytes(b"not a dataset")
    args = [command, str(path)]
    if command == "html-report":
        args.append(str(tmp_path / "report.html"))
    result = RUNNER.invoke(app, [*args, "--json"])
    assert result.exit_code == 2, result.output
    assert json.loads(result.stdout)


@pytest.mark.parametrize("command", ["crs-scan", "batch", "html-report"])
def test_empty_dataset(command: str, tmp_path: Path) -> None:
    path = tmp_path / "empty.gpkg"
    gpd.GeoDataFrame(geometry=[], crs="EPSG:4326").to_file(path)
    args = [command, str(path)]
    if command == "html-report":
        args.append(str(tmp_path / "empty.html"))
    result = RUNNER.invoke(app, [*args, "--json"])
    assert result.exit_code == 0, result.output


def test_axis_order_and_invalid_arguments() -> None:
    good = ["axis-order", "--bounds", "110", "-8", "111", "-7", "--json"]
    result = RUNNER.invoke(app, good)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"] == "correct"
    assert RUNNER.invoke(app, good).stdout == result.stdout
    swapped = RUNNER.invoke(app, ["axis-order", "--bounds", "-8", "110", "-7", "111", "--json"])
    assert swapped.exit_code == 1
    assert json.loads(swapped.stdout)["status"] == "likely_swapped"
    assert RUNNER.invoke(app, ["axis-order", "--bounds", "0", "0", "0", "0"]).exit_code == 2
    ambiguous = RUNNER.invoke(app, ["axis-order", "--bounds", "1", "2", "3", "4", "--json"])
    assert ambiguous.exit_code == 1
    assert json.loads(ambiguous.stdout)["status"] == "ambiguous"
    assert RUNNER.invoke(app, ["axis-order", "--bounds", "bad"]).exit_code == 2
    assert RUNNER.invoke(app, ["crs-scan", "--unknown"]).exit_code == 2


def test_datum_shift() -> None:
    args = ["datum-shift", "EPSG:4326", "EPSG:4326", "--bounds", "110", "-8", "111", "-7", "--json"]
    result = RUNNER.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"] == "normal"
    assert RUNNER.invoke(app, args).stdout == result.stdout
    assert RUNNER.invoke(app, [*args, "--grid-size", "1"]).exit_code == 2
    args[1] = "invalid-crs"
    assert RUNNER.invoke(app, args).exit_code == 2


def test_suspicious_datum_shift_content(monkeypatch: pytest.MonkeyPatch) -> None:
    evidence = DatumTransformationEvidence(
        source_crs="EPSG:4267",
        target_crs="EPSG:4326",
        operation_name="test operation",
        declared_accuracy_m=1.0,
        best_operation_available=True,
        uses_ballpark_transformation=False,
        missing_grids=(),
        samples=(DatumShiftSample(0, 0, 0.001, 0, 111.0),),
    )
    monkeypatch.setattr(
        PyprojDatumTransformationInspector,
        "inspect",
        lambda *args, **kwargs: evidence,
    )
    result = RUNNER.invoke(
        app,
        [
            "datum-shift",
            "EPSG:4267",
            "EPSG:4326",
            "--bounds",
            "-1",
            "-1",
            "1",
            "1",
            "--json",
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "abnormal"
    assert payload["maximum_shift_m"] == 111.0


def test_batch_partial_failure_and_empty_folder(dataset: Path, tmp_path: Path) -> None:
    bad = tmp_path / "bad.gpkg"
    bad.write_bytes(b"broken")
    result = RUNNER.invoke(app, ["batch", str(tmp_path), "--json"])
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["total"] == 2
    assert [item["exit_code"] for item in payload["items"]] == [2, 0]
    empty = tmp_path / "empty"
    empty.mkdir()
    assert RUNNER.invoke(app, ["batch", str(empty)]).exit_code == 2


def test_batch_recursive_discovery_and_missing_crs(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    source = nested / "unknown.gpkg"
    gpd.GeoDataFrame(geometry=[Point(1, 2)]).to_file(source, driver="GPKG")

    shallow = RUNNER.invoke(app, ["batch", str(tmp_path), "--json"])
    assert shallow.exit_code == 2
    recursive = RUNNER.invoke(app, ["batch", str(tmp_path), "--recursive", "--json"])
    assert recursive.exit_code == 1
    item = json.loads(recursive.stdout)["items"][0]
    assert item["result"]["issues"][0]["code"] == "META-MISSING_CRS"


def test_crs_scan_is_order_independent_and_preserves_missing_crs(tmp_path: Path) -> None:
    wgs84 = tmp_path / "z-wgs84.gpkg"
    mercator = tmp_path / "a-mercator.gpkg"
    missing = tmp_path / "m-missing.gpkg"
    gpd.GeoDataFrame(geometry=[Point(1, 2)], crs="EPSG:4326").to_file(wgs84)
    gpd.GeoDataFrame(geometry=[Point(1, 2)], crs="EPSG:3857").to_file(mercator)
    gpd.GeoDataFrame(geometry=[Point(1, 2)]).to_file(missing)

    first = RUNNER.invoke(app, ["crs-scan", str(wgs84), str(missing), str(mercator), "--json"])
    second = RUNNER.invoke(app, ["crs-scan", str(mercator), str(wgs84), str(missing), "--json"])
    assert first.exit_code == second.exit_code == 1
    assert first.stdout == second.stdout
    statuses = [item["status"] for item in json.loads(first.stdout)["datasets"]]
    assert statuses == ["consistent", "missing", "mismatch"]


def test_html_creation_overwrite_and_quality_gate(dataset: Path, tmp_path: Path) -> None:
    target = tmp_path / "nested" / "report.html"
    args = ["html-report", str(dataset), str(target), "--json"]
    result = RUNNER.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "GeoQC" in target.read_text(encoding="utf-8")
    before = target.read_bytes()
    assert RUNNER.invoke(app, args).exit_code == 2
    assert target.read_bytes() == before
    assert RUNNER.invoke(app, [*args, "--overwrite"]).exit_code == 0
    assert (
        RUNNER.invoke(app, ["html-report", str(dataset), str(tmp_path / "bad.txt")]).exit_code == 2
    )
    duplicate = tmp_path / "duplicates.gpkg"
    gpd.GeoDataFrame(geometry=[Point(1, 2), Point(1, 2)], crs="EPSG:4326").to_file(duplicate)
    failed = RUNNER.invoke(app, ["batch", str(duplicate), "--json"])
    assert failed.exit_code == 1
    item = json.loads(failed.stdout)["items"][0]
    assert item["exit_code"] == 1
    assert item["result"]["issues"][0]["code"] == "TOP-NO-DUPLICATE"

    report = RUNNER.invoke(
        app,
        ["html-report", str(duplicate), str(tmp_path / "duplicate.html"), "--json"],
    )
    assert report.exit_code == 1
    assert json.loads(report.stdout)["quality_gate"] == "failed"


def test_html_atomic_failure_preserves_existing_file(
    dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "report.html"
    destination.write_text("keep me", encoding="utf-8")

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("simulated renderer failure")

    monkeypatch.setattr(HtmlReportRenderer, "write", fail)
    result = RUNNER.invoke(
        app,
        ["html-report", str(dataset), str(destination), "--overwrite", "--json"],
    )
    assert result.exit_code == 2
    assert destination.read_text(encoding="utf-8") == "keep me"


@pytest.mark.parametrize("command", ["batch", "html-report"])
def test_internal_failure_is_sanitized(
    command: str, dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("private implementation detail")

    monkeypatch.setattr(delivery, "audit_dataset", fail)
    args = [command, str(dataset)]
    if command == "html-report":
        args.append(str(tmp_path / "report.html"))
    result = RUNNER.invoke(app, [*args, "--json"])
    assert result.exit_code == 3, result.output
    assert "private implementation" not in result.stdout
    assert "internal_error" in result.stdout


@pytest.mark.parametrize(
    ("command", "target"),
    [
        (["crs-scan", "dataset.gpkg"], (CrsConsistencyScanner, "scan")),
        (
            ["axis-order", "--bounds", "110", "-8", "111", "-7"],
            (AxisOrderDetector, "detect"),
        ),
        (
            [
                "datum-shift",
                "EPSG:4326",
                "EPSG:4326",
                "--bounds",
                "110",
                "-8",
                "111",
                "-7",
            ],
            (DatumShiftDetector, "detect"),
        ),
    ],
)
def test_service_internal_failure_is_exit_three(
    command: list[str],
    target: tuple[type[object], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("sensitive service detail")

    monkeypatch.setattr(target[0], target[1], fail)
    result = RUNNER.invoke(app, [*command, "--json"])
    assert result.exit_code == 3
    assert json.loads(result.stdout) == {
        "error": "Unexpected internal failure.",
        "status": "internal_error",
    }
