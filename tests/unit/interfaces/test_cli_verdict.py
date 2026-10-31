from types import SimpleNamespace

import pytest

from geoqc.application.scoring_service import score_issues
from geoqc.domain.models.topology import DatasetIssue, IssueGeometryKind, RepairRisk
from geoqc.domain.rules import Severity
from geoqc.interfaces.cli.main import _echo_verdict


def _issue(code: str, index: int | None, severity: Severity = Severity.ERROR) -> DatasetIssue:
    return DatasetIssue(
        code=code,
        issue_type=code.lower(),
        title=code,
        message=code,
        severity=severity,
        category="topology" if index is not None else "crs",
        recommendation="fix",
        repair_risk=next(iter(RepairRisk)),
        geometry_kind=next(iter(IssueGeometryKind)),
        geometry_wkt="POINT (0 0)",
        feature_index=index,
    )


def test_verdict_counts_affected_features(capsys: pytest.CaptureFixture[str]) -> None:
    issues = tuple(_issue("OVERLAP", i) for i in range(982))
    result = SimpleNamespace(issues=issues, feature_count=99856)

    _echo_verdict(result, passed=False)  # type: ignore[arg-type]

    out = capsys.readouterr().out
    assert "982 of 99856 features have errors (1.0%)" in out
    assert "score" not in out
    assert "Dataset-level" not in out


def test_verdict_lists_crs_as_dataset_level(capsys: pytest.CaptureFixture[str]) -> None:
    result = SimpleNamespace(
        issues=(_issue("CRS_MISSING", None, Severity.WARNING),), feature_count=10
    )

    _echo_verdict(result, passed=False)  # type: ignore[arg-type]

    out = capsys.readouterr().out
    assert "Dataset-level:" in out
    assert "CRS_MISSING" in out
    assert "features have errors" not in out
    assert "100/100" not in out


def test_score_never_100_with_errors() -> None:
    issues = [_issue("OVERLAP", 0)]
    _, _, overall = score_issues(issues, 10_000_000)

    assert overall < 100
    assert overall == round(overall, 1)
