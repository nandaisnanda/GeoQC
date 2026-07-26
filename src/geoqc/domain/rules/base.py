"""Structural contract implemented by every GeoQC rule."""

from typing import Protocol, TypeVar, runtime_checkable

from geoqc.domain.rules.models import RuleCategory, RuleResult, Severity

ContextT_contra = TypeVar("ContextT_contra", contravariant=True)


@runtime_checkable
class Rule(Protocol[ContextT_contra]):
    """Framework-independent and structurally typed quality rule."""

    id: str
    name: str
    description: str
    severity: Severity
    category: RuleCategory

    def execute(self, context: ContextT_contra) -> RuleResult:
        """Evaluate one context and return a result for this rule."""
        ...
