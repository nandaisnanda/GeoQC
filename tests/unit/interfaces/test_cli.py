"""Tests for the Typer composition root."""

from pathlib import Path

from pytest import MonkeyPatch
from typer.testing import CliRunner

from geoqc.application.engine_selection import DatasetProfile, EngineDecision
from geoqc.application.parallel import ParallelBatchExecutor
from geoqc.application.streaming.geometry import GeometryAuditResult
from geoqc.domain.models import BatchItemResult, BatchItemStatus, BatchResult
from geoqc.infrastructure.gis.parallel_audit import DatasetAudit
from geoqc.interfaces.cli.main import app

runner = CliRunner()


def test_audit_folder_reports_dataset_results(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "roads.gpkg"
    source.touch()
    audit_result = GeometryAuditResult(
        feature_count=2,
        invalid_feature_count=0,
        issue_counts={},
        findings=(),
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
    assert "total=1 succeeded=1 failed=0" in result.stdout


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
