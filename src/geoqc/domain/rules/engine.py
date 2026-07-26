"""Orchestrator for deterministic, extensible rule execution."""

from collections.abc import Iterable
from enum import StrEnum

from geoqc.domain.exceptions import InvalidRuleResultError, RuleExecutionError
from geoqc.domain.rules.base import Rule
from geoqc.domain.rules.models import EngineResult, RuleResult
from geoqc.domain.rules.registry import RuleRegistry


class ErrorPolicy(StrEnum):
    """Control whether an individual rule error stops the run."""

    CONTINUE = "continue"
    RAISE = "raise"


class RuleEngine[ContextT]:
    """Execute injected rules; adding a rule never requires engine changes."""

    def __init__(
        self,
        registry: RuleRegistry[ContextT],
        *,
        error_policy: ErrorPolicy = ErrorPolicy.CONTINUE,
    ) -> None:
        self._registry = registry
        self._error_policy = error_policy

    def execute(
        self,
        context: ContextT,
        *,
        rule_ids: Iterable[str] | None = None,
    ) -> EngineResult:
        """Execute selected rules in deterministic registry/request order."""
        results = tuple(
            self._execute_rule(rule, context) for rule in self._registry.select(rule_ids)
        )
        return EngineResult(results=results)

    def _execute_rule(self, rule: Rule[ContextT], context: ContextT) -> RuleResult:
        try:
            result = rule.execute(context)
        except Exception as error:
            if self._error_policy is ErrorPolicy.RAISE:
                raise RuleExecutionError(rule.id, error) from error
            return RuleResult.errored(rule.id, str(error))

        if result.rule_id != rule.id:
            raise InvalidRuleResultError(
                f"Rule {rule.id!r} returned a result for {result.rule_id!r}"
            )
        return result
