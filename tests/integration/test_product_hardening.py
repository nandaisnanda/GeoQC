"""Product-level invariants for the canonical P1 audit workflow."""

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import pytest
import yaml  # type: ignore[import-untyped]
from shapely.geometry import Point
from typer.testing import CliRunner

import geoqc
from geoqc.domain.rules import Severity
from geoqc.infrastructure.gis.quality_workflow import score_issues
from geoqc.interfaces.cli.main import app


def _issue(index: int | None, *, severity: Severity = Severity.ERROR) -> geoqc.DatasetIssue:
    return geoqc.DatasetIssue(
        code="GEO-TEST",
        issue_type="test",
        title="Test finding",
        message="A test finding.",
        severity=severity,
        category="geometry",
        recommendation="Review the feature.",
        repair_risk=geoqc.RepairRisk.REVIEW,
        geometry_kind=geoqc.IssueGeometryKind.POINT,
        geometry_wkt=f"POINT ({index or 0} 0)",
        layer="features",
        feature_index=index,
        check_name="geometry",
    )


def _write_points(path: Path, *, crs: str | None = "EPSG:3857") -> None:
    gpd.GeoDataFrame({"id": [1, 2]}, geometry=[Point(0, 0), Point(1, 1)], crs=crs).to_file(
        path, driver="GPKG"
    )


def test_scoring_is_size_normalized_for_equal_affected_proportions() -> None:
    small = tuple(_issue(index) for index in range(1))
    large = tuple(_issue(index) for index in range(100))

    assert score_issues(small, 10)[2] == score_issues(large, 1_000)[2]


def test_scoring_caps_repeated_findings_and_stays_in_bounds() -> None:
    repeated = tuple(_issue(0) for _ in range(100))
    policy = geoqc.ScoringPolicy(
        category_weights={"geometry": 1.0},
        category_caps={"geometry": 80.0},
        repeated_feature_cap=30.0,
    )

    scores, deductions, overall = score_issues(repeated, 1, policy)

    assert scores[0].score == 70.0
    assert sum(item.points for item in deductions) == 30.0
    assert 0 <= overall <= 100
    assert all("affected proportion" in item.explanation for item in deductions)


def test_dataset_wide_finding_is_not_diluted_by_dataset_size() -> None:
    assert (
        score_issues((_issue(None, severity=Severity.CRITICAL),), 1)[2]
        == score_issues((_issue(None, severity=Severity.CRITICAL),), 1_000_000)[2]
    )


@pytest.mark.parametrize(
    ("profile", "field"),
    [
        ({"name": "bad", "crs": {"required": "yes"}}, "crs.required"),
        ({"name": "bad", "crs": {"surprise": True}}, "crs"),
        ({"name": "bad", "tolerance": "nan"}, "tolerance"),
        ({"name": "bad", "scoring": {"mystery": 1}}, "scoring"),
    ],
)
def test_profile_errors_identify_unsafe_or_unknown_field(
    profile: dict[str, object], field: str
) -> None:
    with pytest.raises(ValueError, match=field):
        geoqc.quality_profile_from_dict(profile)


@pytest.mark.parametrize(
    "profile",
    [
        {"name": "bad", "attribute_schema": {}, "attribute_rules": []},
        {"name": "bad", "enabled_checks": "geometry"},
        {"name": "bad", "version": 1.5},
        {"name": "bad", "version": "not-a-number"},
        {"name": "bad", "tolerance": []},
        {"name": "bad", "severity_overrides": []},
    ],
)
def test_profile_rejects_ambiguous_or_wrongly_typed_values(
    profile: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        geoqc.quality_profile_from_dict(profile)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: geoqc.TopologyRule(geoqc.TopologyRuleType.NO_OVERLAP, ""),
        lambda: geoqc.TopologyRule(geoqc.TopologyRuleType.MUST_BE_INSIDE, "features"),
        lambda: geoqc.TopologyRule(geoqc.TopologyRuleType.NO_SPIKES, "features", minimum_angle=0),
        lambda: geoqc.TopologyRule(
            geoqc.TopologyRuleType.PRECISION_GRID, "features", precision_grid_size=0
        ),
        lambda: geoqc.ScoringPolicy(category_weights={"geometry": 1}, category_caps={"other": 10}),
        lambda: geoqc.ScoringPolicy(repeated_feature_cap=101),
        lambda: geoqc.QualityProfile("bad", enabled_checks=("imaginary",)),
        lambda: geoqc.QualityProfile("bad", expected_geometry_types=("",)),
        lambda: geoqc.QualityGatePolicy(minimum_score=101),
    ],
)
def test_policy_models_reject_unsafe_boundaries(factory: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        factory()


def test_equivalent_yaml_and_json_profiles_produce_identical_results(tmp_path: Path) -> None:
    source = tmp_path / "points.gpkg"
    _write_points(source)
    profile = {
        "name": "points",
        "expected_geometry_types": ["Point"],
        "crs": {"required": True, "require_projected": True, "allowed": []},
    }
    json_profile = tmp_path / "profile.json"
    yaml_profile = tmp_path / "profile.yaml"
    json_profile.write_text(json.dumps(profile), encoding="utf-8")
    yaml_profile.write_text(yaml.safe_dump(profile), encoding="utf-8")

    json_result = geoqc.audit_dataset(source, profile=json_profile)
    yaml_result = geoqc.audit_dataset(source, profile=yaml_profile)

    assert json_result.to_dict() == yaml_result.to_dict()


def test_metric_threshold_is_skipped_with_actionable_crs_reason(tmp_path: Path) -> None:
    source = tmp_path / "angular.gpkg"
    _write_points(source, crs="EPSG:4326")
    profile = geoqc.QualityProfile(name="metric", tolerance=1.0)

    result = geoqc.audit_dataset(source, profile=profile)

    topology = result.check("topology")
    assert topology.status is geoqc.CheckStatus.SKIPPED
    assert "projected CRS" in (topology.reason or "")


def test_missing_crs_metric_profile_and_expected_geometry_are_explicit(tmp_path: Path) -> None:
    source = tmp_path / "points.gpkg"
    _write_points(source, crs=None)
    profile = geoqc.QualityProfile(
        name="lines",
        tolerance=1,
        expected_geometry_types=("LineString",),
    )

    result = geoqc.audit_dataset(source, profile=profile)

    assert result.check("topology").status is geoqc.CheckStatus.SKIPPED
    assert any(issue.code == "GEO-UNEXPECTED-TYPE" for issue in result.issues)
    assert not result.passes()


def test_profile_runs_local_topology_attribute_and_allowed_crs_checks(tmp_path: Path) -> None:
    source = tmp_path / "duplicates.gpkg"
    gpd.GeoDataFrame({"id": [1, 1]}, geometry=[Point(0, 0), Point(0, 0)], crs="EPSG:3857").to_file(
        source, driver="GPKG"
    )
    profile = geoqc.QualityProfile(
        name="strict",
        allowed_crs=("EPSG:32648",),
        topology_rules=(geoqc.TopologyRule(geoqc.TopologyRuleType.NO_DUPLICATE, "duplicates"),),
        attribute_rules=(geoqc.AttributeRule("missing", geoqc.AttributeRuleType.REQUIRED),),
    )

    result = geoqc.audit_dataset(source, profile=profile)

    codes = {issue.code for issue in result.issues}
    assert "ATTR-REQUIRED" in codes
    assert "META-DISALLOWED_CRS" in codes
    assert result.check("topology").status is geoqc.CheckStatus.FAILED


def test_builtin_profile_name_and_result_numeric_boundaries(tmp_path: Path) -> None:
    source = tmp_path / "points.gpkg"
    _write_points(source)
    result = geoqc.audit_dataset(source, profile="road-network")

    assert result.profile_name == "road-network"
    with pytest.raises(ValueError, match="feature_count"):
        replace(result, feature_count=-1)
    with pytest.raises(ValueError, match="quality_score"):
        replace(result, quality_score=100.01)


def test_result_exports_are_atomic_deterministic_and_non_overwriting(tmp_path: Path) -> None:
    source = tmp_path / "invalid.gpkg"
    _write_points(source, crs=None)
    result = geoqc.audit_dataset(source)
    json_path = tmp_path / "report.json"
    html_path = tmp_path / "report.html"
    findings_path = tmp_path / "findings.gpkg"

    result.to_json(json_path)
    first_json = json_path.read_bytes()
    json_path.unlink()
    result.to_json(json_path)
    result.to_html(html_path)
    result.write_findings(findings_path)

    assert json_path.read_bytes() == first_json
    assert json.loads(first_json)["schema_version"] == "1.0"
    assert result.dataset_name in html_path.read_text(encoding="utf-8")
    findings = gpd.read_file(findings_path)
    assert {
        "check_name",
        "code",
        "severity",
        "recommendation",
        "layer",
        "feature_index",
    } <= set(findings.columns)
    with pytest.raises(FileExistsError):
        result.to_json(json_path)
    result.to_json(json_path, overwrite=True)


def test_in_memory_result_explains_export_boundary() -> None:
    result = geoqc.audit_geometries([Point(0, 0)])

    with pytest.raises(RuntimeError, match="file audit result"):
        result.to_json("unused.json")


def test_audit_cli_exports_and_uses_quality_exit_codes(tmp_path: Path) -> None:
    source = tmp_path / "points.gpkg"
    _write_points(source)
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "name: points\ncrs:\n  required: true\n  require_projected: true\n  allowed: []\n",
        encoding="utf-8",
    )
    report = tmp_path / "report.html"
    json_path = tmp_path / "report.json"
    findings = tmp_path / "findings.gpkg"

    passed = CliRunner().invoke(
        app,
        [
            "audit",
            str(source),
            "--profile",
            str(profile),
            "--report",
            str(report),
            "--json",
            str(json_path),
            "--findings",
            str(findings),
        ],
    )

    assert passed.exit_code == 0
    assert "PROCESSED" in passed.stdout and "QUALITY PASS" in passed.stdout
    assert report.is_file() and json_path.is_file() and findings.is_file()

    missing_crs = tmp_path / "missing-crs.gpkg"
    _write_points(missing_crs, crs=None)
    failed = CliRunner().invoke(
        app, ["audit", str(missing_crs), "--json", str(tmp_path / "f.json")]
    )
    assert failed.exit_code == 1
    assert "QUALITY FAIL" in failed.stdout
    assert "OK" not in failed.stdout


def test_audit_cli_invalid_profile_and_malformed_dataset_exit_two(tmp_path: Path) -> None:
    source = tmp_path / "points.gpkg"
    _write_points(source)
    invalid_profile = tmp_path / "bad.yaml"
    invalid_profile.write_text("name: bad\nunknown: true\n", encoding="utf-8")

    invalid = CliRunner().invoke(app, ["audit", str(source), "--profile", str(invalid_profile)])
    malformed = tmp_path / "broken.geojson"
    malformed.write_text("not json", encoding="utf-8")
    unreadable = CliRunner().invoke(
        app, ["audit", str(malformed), "--json", str(tmp_path / "broken.json")]
    )

    assert invalid.exit_code == 2 and "unknown quality profile fields" in invalid.stderr
    assert unreadable.exit_code == 2 and "Error:" in unreadable.stderr
