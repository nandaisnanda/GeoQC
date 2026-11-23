"""`geoqc check` flags CRS differences between layers of one GeoPackage."""

import hashlib
import json
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import pyogrio  # type: ignore[import-untyped]
import pytest
from shapely.geometry import Point
from typer.testing import CliRunner

from geoqc.application.services.crs_scanner import layer_crs_mismatch_issues
from geoqc.domain.exceptions import DatasetMetadataReadError
from geoqc.domain.models import CrsMetadata, DatasetCrsMetadata, DatasetSource
from geoqc.domain.rules import FindingKind, ProvenanceOrigin, Severity
from geoqc.infrastructure.gis.dataset_audit import audit_geodataframe, with_extra_issues
from geoqc.infrastructure.gis.dataset_export import write_audit_report
from geoqc.infrastructure.gis.pyogrio_crs_reader import PyogrioCrsMetadataReader
from geoqc.interfaces.cli.main import app

CODE = "CRS-LAYER-MISMATCH"


def _layer(crs: str | None) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(geometry=[Point(0, 0), Point(1, 1)], crs=crs)


def _write(path: Path, layers: dict[str, str | None]) -> None:
    for name, crs in layers.items():
        _layer(crs).to_file(path, layer=name, driver="GPKG")


def _check(source: Path) -> tuple[int, str]:
    with pytest.warns(DeprecationWarning, match="geoqc check is deprecated"):
        result = CliRunner().invoke(app, ["check", str(source), "--preset", "point_survey"])
    return result.exit_code, result.stdout


def _outputs(source: Path, layer: str) -> tuple[Path, Path]:
    folder = source.parent / "geoqc_output"
    return (
        folder / f"{source.stem}_{layer}_issues.gpkg",
        folder / f"{source.stem}_{layer}_report.html",
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_two_crs_layers_give_one_warning_in_terminal_gpkg_and_html(tmp_path: Path) -> None:
    source = tmp_path / "multi.gpkg"
    _write(source, {"a_geo": "EPSG:4326", "b_utm": "EPSG:32749"})
    before = _digest(source)

    code, stdout = _check(source)

    assert code == 0
    assert stdout.count("CRS: Layer 'b_utm' uses EPSG:32749") == 1
    assert "no CRS was assigned" in stdout.replace("\n", " ")
    mismatch_gpkg, mismatch_html = _outputs(source, "b_utm")
    frame = gpd.read_file(mismatch_gpkg, layer="geoqc_errors_point")
    found = frame[frame["code"] == CODE]
    assert len(found) == 1
    row = found.iloc[0]
    assert row["severity"] == "warning"
    assert row["kind"] == "rule_violation"
    assert row["rule_version"] == "1.0.0"
    assert row["provenance_origin"] == "built-in"
    assert CODE in mismatch_html.read_text(encoding="utf-8")
    clean_gpkg, clean_html = _outputs(source, "a_geo")
    assert CODE not in clean_html.read_text(encoding="utf-8")
    for name in pyogrio.list_layers(clean_gpkg)[:, 0]:
        clean = gpd.read_file(clean_gpkg, layer=name)
        assert "code" not in clean or CODE not in set(clean["code"])
    assert _digest(source) == before
    assert gpd.read_file(source, layer="b_utm").crs.to_epsg() == 32749


def test_same_crs_layers_give_no_finding(tmp_path: Path) -> None:
    source = tmp_path / "multi.gpkg"
    _write(source, {"a": "EPSG:32749", "b": "EPSG:32749"})

    _, stdout = _check(source)

    assert "CRS:" not in stdout
    for layer in ("a", "b"):
        _, html = _outputs(source, layer)
        assert CODE not in html.read_text(encoding="utf-8")


def test_layer_without_crs_is_not_a_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "multi.gpkg"
    _write(source, {"a_geo": "EPSG:4326", "b_none": None})

    _, stdout = _check(source)

    assert "CRS: Layer" not in stdout
    gpkg, html = _outputs(source, "b_none")
    assert CODE not in html.read_text(encoding="utf-8")
    assert "META-MISSING_CRS" in html.read_text(encoding="utf-8")
    frame = gpd.read_file(gpkg, layer="geoqc_errors_point")
    assert CODE not in set(frame["code"])
    assert "META-MISSING_CRS" in set(frame["code"])


def test_json_report_carries_the_finding(tmp_path: Path) -> None:
    source = tmp_path / "multi.gpkg"
    _write(source, {"a_geo": "EPSG:4326", "b_utm": "EPSG:32749"})
    issues = layer_crs_mismatch_issues(
        [DatasetSource(str(source), "a_geo"), DatasetSource(str(source), "b_utm")],
        PyogrioCrsMetadataReader(),
    )
    base = audit_geodataframe(_layer("EPSG:32749"), dataset_name="b_utm")
    result = with_extra_issues(base, [issues["b_utm"]], None)

    path = write_audit_report(result, tmp_path / "report.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    found = [item for item in payload["issues"] if item["code"] == CODE]

    assert len(found) == 1
    assert found[0]["severity"] == "warning"
    assert found[0]["kind"] == "rule_violation"
    assert found[0]["rule_version"] == "1.0.0"
    assert found[0]["provenance"] == {"origin": "built-in", "source": "geoqc"}
    assert result.quality_score < base.quality_score
    assert with_extra_issues(base, [], None) is base


def test_finding_fields_and_baseline_selection(tmp_path: Path) -> None:
    source = tmp_path / "multi.gpkg"
    _write(source, {"b": "EPSG:32749", "a": "EPSG:4326", "c": "EPSG:4326"})

    issues = layer_crs_mismatch_issues(
        [DatasetSource(str(source), name) for name in ("b", "a", "c")],
        PyogrioCrsMetadataReader(),
    )

    assert set(issues) == {"b"}
    issue = issues["b"]
    assert issue.code == CODE
    assert issue.severity is Severity.WARNING
    assert issue.kind is FindingKind.RULE_VIOLATION
    assert issue.rule_version == "1.0.0"
    assert issue.provenance.origin is ProvenanceOrigin.BUILT_IN
    assert issue.metadata["baseline_layer"] == "a"


class _FailingReader:
    def read(self, source: DatasetSource) -> DatasetCrsMetadata:
        raise DatasetMetadataReadError(source.identifier, "boom")


class _FixedReader:
    def read(self, source: DatasetSource) -> DatasetCrsMetadata:
        return DatasetCrsMetadata(source=source, crs=None)


def test_no_findings_without_a_valid_baseline() -> None:
    sources = [DatasetSource("x.gpkg", "a"), DatasetSource("x.gpkg", "b")]
    assert layer_crs_mismatch_issues(sources, _FailingReader()) == {}
    assert layer_crs_mismatch_issues(sources, _FixedReader()) == {}


def test_single_layer_gives_no_finding() -> None:
    class Same:
        def read(self, source: DatasetSource) -> DatasetCrsMetadata:
            return DatasetCrsMetadata(source=source, crs=CrsMetadata('PROJCS["x"]', "EPSG:1"))

    assert layer_crs_mismatch_issues([DatasetSource("x.gpkg", "a")], Same()) == {}
