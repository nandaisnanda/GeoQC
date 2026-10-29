"""Tests for the Typer composition root."""

import json
import pickle
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import pytest
from pytest import MonkeyPatch
from shapely.geometry import Point
from typer.testing import CliRunner

from geoqc.application.engine_selection import DatasetProfile, EngineDecision
from geoqc.application.parallel import ParallelBatchExecutor
from geoqc.domain.models import (
    BatchItemResult,
    BatchItemStatus,
    BatchResult,
)
from geoqc.domain.models.topology import DatasetIssue, IssueGeometryKind, RepairRisk
from geoqc.domain.rules import Severity
from geoqc.infrastructure.gis.parallel_audit import DatasetAudit
from geoqc.infrastructure.gis.quality_workflow import audit_geometries
from geoqc.infrastructure.gis.road_dataset_repair import (
    RoadDatasetRepairer,
    RoadDatasetRepairResult,
)
from geoqc.interfaces.cli.main import app

runner = CliRunner()


def test_audit_folder_reports_dataset_results(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "roads.gpkg"
    source.touch()
    audit_result = audit_geometries(
        (Point(0, 0), Point(1, 1)), dataset_name="roads", crs="EPSG:3857"
    )
    decision = EngineDecision(
        engine="streaming",
        reasons=("test",),
        profile=DatasetProfile(
            driver="GPKG",
            size_bytes=0,
            feature_count=2,
            estimated_memory_bytes=0,
            available_memory_bytes=None,
        ),
    )
    batch = BatchResult(
        (
            BatchItemResult(
                source=str(source),
                status=BatchItemStatus.SUCCEEDED,
                value=DatasetAudit(audit_result, decision),
            ),
        )
    )
    monkeypatch.setattr(ParallelBatchExecutor, "run", lambda *_args, **_kwargs: batch)

    result = runner.invoke(app, ["audit", str(tmp_path)])

    assert result.exit_code == 0
    assert "engine=streaming features=2 invalid=0" in result.stdout
    assert "status=passed issues=0" in result.stdout
    assert "total=1 succeeded=1 failed=0" in result.stdout


def test_audit_folder_reports_each_geopackage_layer(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "multi.gpkg"
    for name in ("first", "second"):
        gpd.GeoDataFrame(geometry=[Point(0, 0)], crs="EPSG:4326").to_file(source, layer=name)
    pooled: list[Path] = []

    def fake_run(
        _self: object, sources: tuple[Path, ...], *_args: object, **_kwargs: object
    ) -> BatchResult[DatasetAudit]:
        pooled.extend(sources)
        return BatchResult(())

    monkeypatch.setattr(ParallelBatchExecutor, "run", fake_run)

    result = runner.invoke(app, ["audit", str(tmp_path)])

    assert pooled == []
    assert "FAILED" not in result.stdout
    assert f"QUALITY PASS {source.resolve()} layer=first" in result.stdout
    assert f"QUALITY PASS {source.resolve()} layer=second" in result.stdout
    assert "total=2 succeeded=2 failed=0" in result.stdout
    assert result.exit_code == 0


def test_dataset_issue_survives_pickling() -> None:
    issue = DatasetIssue(
        code="GEOM_001",
        issue_type="invalid_geometry",
        title="Invalid geometry",
        message="Self-intersection",
        severity=Severity.ERROR,
        category="geometry",
        recommendation="Run make_valid",
        repair_risk=next(iter(RepairRisk)),
        geometry_kind=next(iter(IssueGeometryKind)),
        geometry_wkt="POINT (0 0)",
        metadata={"reason": "ring"},
    )

    restored = pickle.loads(pickle.dumps(issue))

    assert restored == issue
    assert restored.metadata["reason"] == "ring"
    with pytest.raises(TypeError):
        restored.metadata["reason"] = "x"


def test_audit_folder_skips_unsupported_files(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    for name in ("roads.gpkg", "rivers.shp", "rivers.dbf", "report.json", "notes.txt"):
        (tmp_path / name).touch()
    seen: list[str] = []

    def fake_run(
        _self: object, sources: tuple[Path, ...], *_args: object, **_kwargs: object
    ) -> BatchResult[DatasetAudit]:
        seen.extend(item.name for item in sources)
        return BatchResult(())

    monkeypatch.setattr(ParallelBatchExecutor, "run", fake_run)

    result = runner.invoke(app, ["audit", str(tmp_path)])

    assert sorted(seen) == ["rivers.shp", "roads.gpkg"]
    assert "FAILED" not in result.stdout
    assert result.stdout.strip().endswith("Skipped 2 unsupported file(s): notes.txt, report.json")


def test_cli_shows_help() -> None:
    """The CLI is discoverable without requiring a business command."""
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "GeoQC GIS quality-control toolkit" in result.stdout


def test_cli_shows_version() -> None:
    """The eager version option reports the installed package version."""
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "GeoQC 0.1.0"


def test_cli_rejects_unknown_options() -> None:
    """Unknown arguments produce a conventional nonzero usage error."""
    result = CliRunner().invoke(app, ["--unknown"])

    assert result.exit_code == 2
    assert "No such option" in result.output


def test_repair_roads_command_writes_report(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "roads.shp"
    output = tmp_path / "repaired.gpkg"
    report = tmp_path / "report.json"
    source.touch()
    summary = RoadDatasetRepairResult(
        source.resolve(), None, output.resolve(), "network", "EPSG:3857", 3, 3, 1, 5
    )
    monkeypatch.setattr(RoadDatasetRepairer, "repair", lambda *_args, **_kwargs: summary)

    result = runner.invoke(
        app,
        [
            "repair-roads",
            str(source),
            str(output),
            "--output-layer",
            "network",
            "--snap-tolerance",
            "0.1",
            "--report",
            str(report),
        ],
    )

    assert result.exit_code == 0
    assert "snapped=1 segments=5" in result.stdout
    assert json.loads(report.read_text(encoding="utf-8"))["output_segment_count"] == 5


def test_repair_roads_command_reports_safe_error(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    def fail(*_args: object, **_kwargs: object) -> RoadDatasetRepairResult:
        raise ValueError("bad road data")

    monkeypatch.setattr(RoadDatasetRepairer, "repair", fail)

    result = runner.invoke(app, ["repair-roads", "in.shp", str(tmp_path / "out.gpkg")])

    assert result.exit_code == 2
    assert "Error: bad road data" in result.stderr
