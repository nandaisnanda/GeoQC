"""Example completeness rule kept separate from the core engine."""

from collections.abc import Sized

from geoqc.domain.rules.models import (
    RuleCategory,
    RuleFinding,
    RuleResult,
    Severity,
)


class NonEmptyRule:
    """Check that a sized dataset contains at least one item."""

    id = "core.completeness.non-empty"
    name = "Non-empty dataset"
    description = "Checks that the supplied dataset contains at least one item."
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS

    def execute(self, context: Sized) -> RuleResult:
        """Return one finding when the supplied dataset is empty."""
        if len(context) == 0:
            return RuleResult.failed(
                self.id,
                RuleFinding(message="Dataset contains no features."),
            )
        return RuleResult.passed(self.id)
