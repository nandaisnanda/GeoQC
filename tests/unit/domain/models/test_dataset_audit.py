"""Tests for deterministic unified dataset audit result models."""

import json

import pytest

from geoqc.domain.models import (
    AuditCheckResult,
    AuditDatasetMetadata,
    AuditIssue,
    CheckStatus,
    DatasetAuditReport,
)
from geoqc.domain.rules import Severity


def _metadata() -> AuditDatasetMetadata:
    return AuditDatasetMetadata(
        "data.gpkg", "roads", "GPKG", "EPSG:3857", 3, "geometry", 12, "streaming"
    )


def test_report_serialization_is_deterministic_and_complete() -> None:
    with pytest.warns(DeprecationWarning, match="AuditIssue is deprecated"):
        issue = AuditIssue("GEO-INVALID", "Invalid.", Severity.ERROR, "Repair it.", (2, 0))
    with pytest.warns(DeprecationWarning, match="DatasetAuditReport is deprecated"):
        report = DatasetAuditReport(
            _metadata(),
            (
                AuditCheckResult("geometry", CheckStatus.FAILED, (issue,)),
                AuditCheckResult("crs", CheckStatus.PASSED),
                AuditCheckResult("attributes", CheckStatus.SKIPPED, reason="No schema."),
            ),
        )

    first = json.dumps(report.to_dict(), separators=(",", ":"))
    second = json.dumps(report.to_dict(), separators=(",", ":"))

    assert first == second
    assert report.status is CheckStatus.FAILED
    assert report.issue_count == 1
    assert report.feature_indices == (0, 2)
    assert issue.to_dict()["recommendation"] == "Repair it."


def test_report_model_enforces_status_invariants() -> None:
    with pytest.raises(ValueError, match="reason"):
        AuditCheckResult("topology", CheckStatus.SKIPPED)
    with pytest.raises(ValueError, match="issue"):
        AuditCheckResult("geometry", CheckStatus.FAILED)
    with (
        pytest.raises(ValueError, match="passed"),
        pytest.warns(DeprecationWarning, match="AuditIssue is deprecated"),
    ):
        AuditCheckResult(
            "geometry",
            CheckStatus.PASSED,
            (AuditIssue("GEO-X", "Bad.", Severity.ERROR, "Fix."),),
        )
    with (
        pytest.raises(ValueError, match="non-negative"),
        pytest.warns(DeprecationWarning, match="AuditIssue is deprecated"),
    ):
        AuditIssue("GEO-X", "Bad.", Severity.ERROR, "Fix.", (-1,))
    with pytest.raises(ValueError, match="counts"):
        AuditCheckResult("geometry", CheckStatus.PASSED, counts={"bad": -1})
    with (
        pytest.raises(ValueError, match="unique"),
        pytest.warns(DeprecationWarning, match="DatasetAuditReport is deprecated"),
    ):
        DatasetAuditReport(
            _metadata(),
            (
                AuditCheckResult("crs", CheckStatus.PASSED),
                AuditCheckResult("crs", CheckStatus.PASSED),
            ),
        )


def test_report_status_precedence_and_missing_check() -> None:
    error = AuditCheckResult("attributes", CheckStatus.ERROR, reason="read failed")
    with pytest.warns(DeprecationWarning, match="DatasetAuditReport is deprecated"):
        report = DatasetAuditReport(
            _metadata(),
            (AuditCheckResult("geometry", CheckStatus.PASSED), error),
        )

    assert report.status is CheckStatus.ERROR
    with pytest.raises(KeyError):
        report.check("missing")
