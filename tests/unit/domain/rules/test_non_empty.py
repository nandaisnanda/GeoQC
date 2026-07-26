"""Tests for the standalone example rule."""

from geoqc.domain.rules import ResultStatus, Rule
from geoqc.domain.rules.examples import NonEmptyRule


def test_non_empty_rule_satisfies_rule_protocol_and_metadata() -> None:
    rule = NonEmptyRule()

    assert isinstance(rule, Rule)
    assert rule.id == "core.completeness.non-empty"
    assert rule.name
    assert rule.description
    assert rule.severity
    assert rule.category


def test_non_empty_rule_reports_empty_dataset() -> None:
    result = NonEmptyRule().execute([])

    assert result.status is ResultStatus.FAILED
    assert result.findings[0].message == "Dataset contains no features."
