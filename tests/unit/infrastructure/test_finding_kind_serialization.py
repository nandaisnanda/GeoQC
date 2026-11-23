"""Finding kind, rule version and provenance reach JSON, GPKG and HTML."""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import pytest
from shapely.geometry import LineString

from geoqc.domain.models import DatasetAuditResult, DatasetIssue, IssueGeometryKind, RepairRisk
from geoqc.domain.rules import FindingKind, Provenance, ProvenanceOrigin, Severity
from geoqc.infrastructure.gis.dataset_audit import audit_geodataframe
from geoqc.infrastructure.gis.dataset_export import write_audit_report, write_issue_layers
from geoqc.infrastructure.gis.profile_loading import load_builtin_preset

LEGACY_COLUMNS = [
    "fingerprint",
    "check_name",
    "code",
    "issue_type",
    "title",
    "message",
    "severity",
    "category",
    "suggested_fix",
    "recommendation",
    "repair_risk",
    "source_layer",
    "layer",
    "feature_index",
    "related_feature_index",
    "feature_id",
    "related_feature_id",
]
NEW_COLUMNS = ["kind", "rule_version", "provenance_origin", "provenance_source"]
LEGACY_JSON_KEYS = {
    "fingerprint",
    "check_name",
    "code",
    "issue_type",
    "title",
    "message",
    "severity",
    "category",
    "recommendation",
    "repair_risk",
    "geometry_kind",
    "geometry_wkt",
    "layer",
    "feature_index",
    "related_feature_index",
    "feature_id",
    "related_feature_id",
    "metadata",
}


def _audit() -> DatasetAuditResult:
    """Grid with an undershoot (warning) and plain road ends (info)."""
    lines = []
    for row in range(3):
        for col in range(2):
            lines.append(LineString([(col * 100, row * 100), ((col + 1) * 100, row * 100)]))
            lines.append(LineString([(row * 100, col * 100), (row * 100, (col + 1) * 100)]))
    lines.append(LineString([(50, 300), (50, 201)]))
    lines.append(LineString([(100, 0), (100, -80)]))
    frame = gpd.GeoDataFrame(geometry=lines, crs="EPSG:32749")
    return audit_geodataframe(frame, dataset_name="jalan", profile=load_builtin_preset("jalan"))


def _issue(**overrides: object) -> DatasetIssue:
    values: dict[str, object] = {
        "code": "GEO-X",
        "issue_type": "x",
        "title": "Title",
        "message": "Message",
        "severity": Severity.ERROR,
        "category": "geometry",
        "recommendation": "Fix it.",
        "repair_risk": RepairRisk.REVIEW,
        "geometry_kind": IssueGeometryKind.POINT,
        "geometry_wkt": "POINT (0 0)",
    }
    values.update(overrides)
    return DatasetIssue(**values)  # type: ignore[arg-type]


def test_dead_end_info_is_contextual_and_warning_is_rule_violation() -> None:
    issues = [i for i in _audit().issues if i.code == "TOP-NO-DANGLES"]
    info = [i for i in issues if i.severity is Severity.INFO]
    warnings_ = [i for i in issues if i.severity is not Severity.INFO]
    assert info
    assert warnings_
    assert all(i.kind is FindingKind.CONTEXTUAL_INCONSISTENCY for i in info)
    assert all(i.kind is FindingKind.RULE_VIOLATION for i in warnings_)


def test_issue_defaults_and_pickle_round_trip() -> None:
    issue = _issue()
    assert issue.kind is FindingKind.RULE_VIOLATION
    assert issue.rule_version == "1.0.0"
    assert issue.provenance == Provenance(ProvenanceOrigin.BUILT_IN, "geoqc")
    custom = _issue(
        kind=FindingKind.AI_SUSPICION,
        rule_version="2.0.0",
        provenance=Provenance(ProvenanceOrigin.PROFILE, "bpn.yaml"),
    )
    assert pickle.loads(pickle.dumps(custom)) == custom


def test_issue_rejects_invalid_rule_version() -> None:
    with pytest.raises(ValueError, match="semver"):
        _issue(rule_version="1.0")


def test_issue_to_dict_keeps_legacy_keys_and_adds_new_ones() -> None:
    payload = _issue(kind=FindingKind.STATISTICAL_ANOMALY).to_dict()
    assert payload.keys() >= LEGACY_JSON_KEYS
    assert list(payload)[-3:] == ["kind", "rule_version", "provenance"]
    assert payload["kind"] == "statistical_anomaly"
    assert payload["provenance"] == {"origin": "built-in", "source": "geoqc"}


def test_json_report_carries_kind_version_and_provenance(tmp_path: Path) -> None:
    path = write_audit_report(_audit(), tmp_path / "report.json")
    issues = json.loads(path.read_text(encoding="utf-8"))["issues"]
    assert issues
    for item in issues:
        assert item.keys() >= LEGACY_JSON_KEYS
        assert item["rule_version"] == "1.0.0"
        assert item["provenance"] == {"origin": "built-in", "source": "geoqc"}
    kinds = {(item["severity"], item["kind"]) for item in issues}
    assert ("info", "contextual_inconsistency") in kinds
    assert not any(severity == "info" and kind == "rule_violation" for severity, kind in kinds)


def test_gpkg_issue_layer_appends_new_columns_without_changing_old_ones(
    tmp_path: Path,
) -> None:
    path = write_issue_layers(_audit(), tmp_path / "issues.gpkg")
    frame = gpd.read_file(path, layer="geoqc_errors_point")
    columns = [name for name in frame.columns if name != "geometry"]
    assert columns[: len(LEGACY_COLUMNS)] == LEGACY_COLUMNS
    assert columns[len(LEGACY_COLUMNS) :] == NEW_COLUMNS
    assert set(frame["rule_version"]) == {"1.0.0"}
    assert set(frame["provenance_origin"]) == {"built-in"}
    assert set(frame["provenance_source"]) == {"geoqc"}
    info = frame[frame["severity"] == "info"]
    assert set(info["kind"]) == {"contextual_inconsistency"}
    assert "rule_violation" in set(frame["kind"])


def test_html_report_shows_kind_version_and_source(tmp_path: Path) -> None:
    path = write_audit_report(_audit(), tmp_path / "report.html")
    html = path.read_text(encoding="utf-8")
    assert "Kind: contextual_inconsistency · Rule v1.0.0 · Source: built-in, geoqc" in html
    assert "Kind: rule_violation" in html
    assert "Recommended action:" in html
