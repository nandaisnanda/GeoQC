"""Tests for orchestration, validation, and failure isolation."""

import pytest

from geoqc.domain.exceptions import InvalidRuleResultError, RuleExecutionError
from geoqc.domain.rules import ErrorPolicy, ResultStatus, RuleEngine, RuleRegistry, RuleResult
from geoqc.domain.rules.examples import NonEmptyRule


class ExplodingRule:
    id = "test.exploding"
    name = "Exploding rule"
    description = "Raises for testing."
    severity = NonEmptyRule.severity
    category = NonEmptyRule.category

    def execute(self, context: list[object]) -> RuleResult:
        raise RuntimeError("boom")


class MismatchedRule(ExplodingRule):
    id = "test.mismatched"

    def execute(self, context: list[object]) -> RuleResult:
        return RuleResult.passed("another-rule")


def test_engine_executes_in_order_and_aggregates_results() -> None:
    registry = RuleRegistry[list[object]]([NonEmptyRule()])
    engine = RuleEngine(registry)

    passed = engine.execute([object()])
    failed = engine.execute([])

    assert passed.results[0].status is ResultStatus.PASSED
    assert passed.has_failures is False
    assert failed.results[0].status is ResultStatus.FAILED
    assert failed.has_failures is True


def test_engine_converts_rule_exception_when_policy_continues() -> None:
    engine = RuleEngine(RuleRegistry[list[object]]([ExplodingRule()]))

    result = engine.execute([]).results[0]

    assert result.status is ResultStatus.ERROR
    assert result.error == "boom"


def test_engine_wraps_rule_exception_when_policy_raises() -> None:
    engine = RuleEngine(
        RuleRegistry[list[object]]([ExplodingRule()]),
        error_policy=ErrorPolicy.RAISE,
    )

    with pytest.raises(RuleExecutionError, match="test.exploding"):
        engine.execute([])


def test_engine_rejects_result_for_another_rule() -> None:
    engine = RuleEngine(RuleRegistry[list[object]]([MismatchedRule()]))

    with pytest.raises(InvalidRuleResultError):
        engine.execute([])
