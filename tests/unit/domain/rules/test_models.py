"""Tests for immutable rule-engine value objects."""

import pytest

from geoqc.domain.rules import ResultStatus, RuleFinding, RuleResult


def test_finding_copies_details_to_prevent_external_mutation() -> None:
    details = {"field": "geometry"}
    finding = RuleFinding("Invalid value", details=details)

    details["field"] = "changed"

    assert finding.details["field"] == "geometry"


@pytest.mark.parametrize(
    ("status", "findings", "error"),
    [
        (ResultStatus.PASSED, (RuleFinding("unexpected"),), None),
        (ResultStatus.FAILED, (), None),
        (ResultStatus.ERROR, (), None),
        (ResultStatus.PASSED, (), "unexpected"),
    ],
)
def test_result_rejects_inconsistent_state(
    status: ResultStatus,
    findings: tuple[RuleFinding, ...],
    error: str | None,
) -> None:
    with pytest.raises(ValueError):
        RuleResult("rule-id", status, findings, error)
