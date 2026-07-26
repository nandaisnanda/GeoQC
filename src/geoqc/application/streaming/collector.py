"""Deterministic aggregation for chunk-level Rule Engine results."""

from collections import OrderedDict

from geoqc.domain.rules.models import EngineResult, ResultStatus, RuleFinding, RuleResult


class RuleResultCollector:
    """Merge chunk-level rule results while preserving first-seen rule order."""

    def __init__(self) -> None:
        self._results: OrderedDict[str, list[RuleResult]] = OrderedDict()

    def add(self, result: object) -> None:
        if not isinstance(result, EngineResult):
            raise TypeError("RuleResultCollector expects EngineResult values")
        for rule_result in result.results:
            self._results.setdefault(rule_result.rule_id, []).append(rule_result)

    def finish(self) -> EngineResult:
        return EngineResult(
            tuple(self._merge(rule_id, partials) for rule_id, partials in self._results.items())
        )

    @staticmethod
    def _merge(rule_id: str, partials: list[RuleResult]) -> RuleResult:
        errors = [partial.error for partial in partials if partial.status is ResultStatus.ERROR]
        if errors:
            return RuleResult.errored(rule_id, "; ".join(error for error in errors if error))
        findings: list[RuleFinding] = [
            finding for partial in partials for finding in partial.findings
        ]
        if findings:
            return RuleResult.failed(rule_id, *findings)
        return RuleResult.passed(rule_id)
