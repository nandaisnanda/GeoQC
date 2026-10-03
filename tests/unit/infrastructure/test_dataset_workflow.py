"""End-to-end tests for the phase-one dataset workflow."""

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import pyogrio  # type: ignore[import-untyped]
import pytest
from shapely import box
from shapely.geometry import Point, Polygon

import geoqc
from geoqc.domain.rules import Severity


def _profile() -> geoqc.QualityProfile:
    return geoqc.QualityProfile(
        name="parcel-delivery",
        id_column="parcel_id",
        preset=geoqc.QualityPreset.PARCEL,
        require_projected_crs=True,
        attribute_rules=(
            geoqc.AttributeRule("parcel_id", geoqc.AttributeRuleType.REQUIRED),
            geoqc.AttributeRule("parcel_id", geoqc.AttributeRuleType.NOT_NULL),
            geoqc.AttributeRule("parcel_id", geoqc.AttributeRuleType.UNIQUE),
            geoqc.AttributeRule(
                "status",
                geoqc.AttributeRuleType.ALLOWED_VALUES,
                allowed_values=("active", "inactive"),
            ),
        ),
        gate=geoqc.QualityGatePolicy(minimum_score=90),
    )


def test_unified_geodataframe_audit_covers_geometry_attributes_crs_and_scoring() -> None:
    frame = gpd.GeoDataFrame(
        {"parcel_id": [1, 1], "status": ["active", "wrong"]},
        geometry=[box(0, 0, 2, 2), box(1, 0, 3, 2)],
        crs="EPSG:4326",
    )

    result = geoqc.audit_geodataframe(frame, dataset_name="parcels", profile=_profile())

    assert {issue.category for issue in result.issues} >= {"topology", "attribute", "metadata"}
    assert {issue.issue_type for issue in result.issues} >= {
        "overlap",
        "unique",
        "allowed_values",
        "geographic_crs",
    }
    assert result.schema_version == "1.0"
    assert result.profile_name == "parcel-delivery"
    assert result.score_deductions
    assert not result.passes(_profile().gate)
    assert result.to_dict()["schema_version"] == "1.0"


def test_issue_fingerprint_ignores_wording_and_severity() -> None:
    result = geoqc.audit_geometries([Point()])
    issue = result.issues[0]

    changed = replace(issue, message="Translated message", severity=Severity.CRITICAL)

    assert changed.fingerprint == issue.fingerprint
    assert len(issue.fingerprint) == 24


def test_profile_id_column_keeps_issue_fingerprint_stable_after_reordering() -> None:
    profile = geoqc.QualityProfile(name="stable", id_column="id", require_crs=False)
    original = gpd.GeoDataFrame({"id": ["A", "B"]}, geometry=[Point(), Point(1, 2)])
    reordered = original.iloc[::-1].reset_index(drop=True)

    first = geoqc.audit_geodataframe(original, profile=profile)
    second = geoqc.audit_geodataframe(reordered, profile=profile)

    assert first.issues[0].feature_id == "A"
    assert first.issues[0].fingerprint == second.issues[0].fingerprint


def test_json_and_yaml_profile_round_trip(tmp_path: Path) -> None:
    for suffix in ("json", "yaml"):
        destination = tmp_path / f"profile.{suffix}"
        geoqc.dump_quality_profile(_profile(), destination)

        loaded = geoqc.load_quality_profile(destination)

        assert loaded.name == "parcel-delivery"
        assert loaded.preset is geoqc.QualityPreset.PARCEL
        assert loaded.attribute_rules == _profile().attribute_rules


def test_profile_parser_rejects_unknown_fields() -> None:
    try:
        geoqc.quality_profile_from_dict({"name": "bad", "unexpected": True})
    except ValueError as error:
        assert "unknown quality profile fields" in str(error)
    else:
        raise AssertionError("invalid profile was accepted")


def test_profile_parser_builds_all_nested_configuration() -> None:
    profile = geoqc.quality_profile_from_dict(
        {
            "name": "complete",
            "version": 2,
            "id_column": "id",
            "preset": "parcel",
            "tolerance": "0.1",
            "minimum_area": 2,
            "crs": {
                "required": True,
                "require_projected": True,
                "allowed": ["EPSG:3857"],
            },
            "topology_rules": [
                {"type": "minimum_area", "layer": "complete", "minimum_area": 3},
                {
                    "type": "attribute_overlap",
                    "layer": "complete",
                    "attribute_column": "zone",
                    "overlap_policy": "allow_equal",
                    "tolerance": 0.01,
                },
                {
                    "type": "precision_grid",
                    "layer": "complete",
                    "precision_grid_size": 0.001,
                },
            ],
            "attribute_rules": [
                {
                    "type": "numeric_range",
                    "column": "value",
                    "minimum": 1,
                    "maximum": 5,
                    "severity": "warning",
                }
            ],
            "scoring": {
                "category_weights": {"geometry": 1},
                "severity_penalties": {
                    "info": 1,
                    "warning": 2,
                    "error": 3,
                    "critical": 4,
                },
            },
            "quality_gate": {
                "minimum_score": 95,
                "fail_on": "warning",
                "allow_unknown_crs": True,
            },
        }
    )

    assert profile.version == 2
    assert profile.topology_rules[0].minimum_area == 3
    assert profile.topology_rules[1].attribute_column == "zone"
    assert profile.topology_rules[1].overlap_policy is geoqc.AttributeOverlapPolicy.ALLOW_EQUAL
    assert profile.topology_rules[2].precision_grid_size == 0.001
    assert profile.attribute_rules[0].maximum == 5
    assert profile.scoring.category_weights == {"geometry": 1}
    assert profile.gate.allow_unknown_crs


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: geoqc.AttributeRule("", geoqc.AttributeRuleType.UNIQUE), "column"),
        (
            lambda: geoqc.AttributeRule(
                "value", geoqc.AttributeRuleType.NUMERIC_RANGE, minimum=2, maximum=1
            ),
            "minimum",
        ),
        (
            lambda: geoqc.AttributeRule("value", geoqc.AttributeRuleType.ALLOWED_VALUES),
            "allowed_values",
        ),
        (lambda: geoqc.QualityProfile(""), "name"),
        (lambda: geoqc.QualityProfile("bad", version=0), "version"),
        (lambda: geoqc.QualityProfile("bad", tolerance=-1), "thresholds"),
        (lambda: geoqc.QualityProfile("bad", id_column=" "), "id_column"),
        (lambda: geoqc.ScoringPolicy(category_weights={}), "weights"),
        (lambda: geoqc.ScoringPolicy(category_weights={"geometry": 0}), "positive"),
        (
            lambda: geoqc.ScoringPolicy(severity_penalties={Severity.ERROR: 1}),
            "every severity",
        ),
    ],
)
def test_workflow_models_reject_invalid_configuration(
    factory: Callable[[], object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


@pytest.mark.parametrize("suffix", ["txt", "toml"])
def test_profile_io_rejects_unsupported_extensions(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"profile.{suffix}"
    path.write_text("name: invalid", encoding="utf-8")

    with pytest.raises(ValueError, match="json.*yaml"):
        geoqc.load_quality_profile(path)
    with pytest.raises(ValueError, match="json.*yaml"):
        geoqc.dump_quality_profile(_profile(), path)


def test_profile_loader_rejects_missing_file_and_non_object_root(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        geoqc.load_quality_profile(tmp_path / "missing.yaml")
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="root must be an object"):
        geoqc.load_quality_profile(invalid)


def test_audit_file_writes_issue_layers_and_json_html_reports(tmp_path: Path) -> None:
    source = tmp_path / "parcels.geojson"
    frame = gpd.GeoDataFrame(
        {"parcel_id": [1, 1], "status": ["active", "wrong"]},
        geometry=[box(0, 0, 2, 2), box(1, 0, 3, 2)],
        crs="EPSG:3857",
    )
    frame.to_file(source, driver="GeoJSON")

    result = geoqc.audit_file(source, profile=_profile())
    issue_path = geoqc.write_issue_layers(result, tmp_path / "issues.gpkg")
    json_path = geoqc.write_audit_report(result, tmp_path / "report.json")
    html_path = geoqc.write_audit_report(result, tmp_path / "report.html")

    layers = {str(item[0]) for item in pyogrio.list_layers(issue_path)}
    assert "geoqc_errors_polygon" in layers
    assert json.loads(json_path.read_text(encoding="utf-8"))["schema_version"] == "1.0"
    assert "GeoQC dataset quality report" in html_path.read_text(encoding="utf-8")


def test_attribute_range_missing_column_and_crs_allowlist_are_unified() -> None:
    frame = gpd.GeoDataFrame(
        {"id": [1, 2], "value": [0, "bad"]},
        geometry=[Point(1, 2), Point(2, 3)],
        crs="EPSG:4326",
    )
    profile = geoqc.QualityProfile(
        name="attributes",
        id_column="id",
        allowed_crs=("EPSG:3857",),
        attribute_rules=(
            geoqc.AttributeRule("missing", geoqc.AttributeRuleType.REQUIRED),
            geoqc.AttributeRule(
                "value", geoqc.AttributeRuleType.NUMERIC_RANGE, minimum=1, maximum=5
            ),
        ),
    )

    result = geoqc.audit_geodataframe(frame, profile=profile)

    assert {issue.issue_type for issue in result.issues} >= {
        "required",
        "numeric_range",
        "disallowed_crs",
    }


def test_missing_crs_and_missing_configured_id_are_rejected() -> None:
    frame = gpd.GeoDataFrame({"value": [1]}, geometry=[Point(1, 2)])
    missing_crs = geoqc.audit_geodataframe(frame, profile=geoqc.QualityProfile("required"))
    assert any(issue.issue_type == "missing_crs" for issue in missing_crs.issues)

    with pytest.raises(ValueError, match="id_column.*missing"):
        geoqc.audit_geodataframe(
            frame,
            profile=geoqc.QualityProfile("ids", id_column="missing", require_crs=False),
        )


def test_audit_file_validates_formats_layers_and_reads_parquet(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        geoqc.audit_file(tmp_path / "missing.geojson")
    unsupported = tmp_path / "data.txt"
    unsupported.write_text("data", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        geoqc.audit_file(unsupported)

    parquet = tmp_path / "points.parquet"
    frame = gpd.GeoDataFrame(geometry=[Point(1, 2)], crs="EPSG:4326")
    frame.to_parquet(parquet)
    assert geoqc.audit_file(parquet).feature_count == 1

    package = tmp_path / "layers.gpkg"
    frame.to_file(package, layer="first", driver="GPKG")
    frame.to_file(package, layer="second", driver="GPKG")
    with pytest.raises(ValueError, match="multiple layers"):
        geoqc.audit_file(package)
    with pytest.raises(ValueError, match="unknown layer"):
        geoqc.audit_file(package, layer="missing")
    assert geoqc.audit_file(package, layer="second").feature_count == 1


def test_outputs_protect_existing_files_and_validate_suffixes(tmp_path: Path) -> None:
    result = geoqc.audit_geometries([Point(1, 2)], crs="EPSG:4326")
    with pytest.raises(ValueError, match="gpkg"):
        geoqc.write_issue_layers(result, tmp_path / "issues.geojson")
    output = geoqc.write_issue_layers(result, tmp_path / "issues.gpkg")
    with pytest.raises(FileExistsError):
        geoqc.write_issue_layers(result, output)
    assert geoqc.write_issue_layers(result, output, overwrite=True) == output
    with pytest.raises(ValueError, match="json or .html"):
        geoqc.write_audit_report(result, tmp_path / "report.txt")


def test_run_quality_workflow_returns_every_artifact(tmp_path: Path) -> None:
    source = tmp_path / "points.geojson"
    gpd.GeoDataFrame({"id": [1, 2]}, geometry=[Point(1, 2), Point(1, 2)], crs="EPSG:4326").to_file(
        source, driver="GeoJSON"
    )

    artifacts = geoqc.run_quality_workflow(
        source,
        profile=geoqc.QualityProfile(name="survey", preset=geoqc.QualityPreset.POINT_SURVEY),
        issue_output=tmp_path / "issues.gpkg",
        report_output=tmp_path / "report.json",
    )

    assert artifacts.result.issues
    assert artifacts.issue_dataset is not None
    assert artifacts.report is not None
    assert Path(artifacts.issue_dataset).exists()


def test_clean_audit_still_writes_valid_empty_issue_geopackage(tmp_path: Path) -> None:
    result = geoqc.audit_geometries([Point(1, 2)], crs="EPSG:4326")

    output = geoqc.write_issue_layers(result, tmp_path / "clean.gpkg")

    assert output.exists()
    assert list(pyogrio.list_layers(output))


def test_repair_plan_marks_competing_reviewed_actions() -> None:
    bowtie = Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])
    result = geoqc.audit_geometries([bowtie])

    plan = geoqc.build_repair_plan(result)

    assert len(plan.actions) >= 2
    assert plan.has_conflicts
    assert not plan.automatic_actions


def test_audit_layers_runs_cross_layer_profile_rules() -> None:
    profile = geoqc.QualityProfile(
        name="building-delivery",
        require_crs=False,
        topology_rules=(
            geoqc.TopologyRule(
                geoqc.TopologyRuleType.MUST_BE_INSIDE,
                "buildings",
                "parcels",
            ),
        ),
    )
    frames = {
        "buildings": gpd.GeoDataFrame(geometry=[box(20, 20, 21, 21)], crs="EPSG:3857"),
        "parcels": gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10)], crs="EPSG:3857"),
    }

    result = geoqc.audit_layers(frames, profile=profile)

    assert any(issue.issue_type == "must_be_inside" for issue in result.issues)
    assert result.feature_count == 2
