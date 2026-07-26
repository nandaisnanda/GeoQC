"""Immutable value objects shared by rules and the rule engine."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

type Scalar = str | int | float | bool | None
type Metadata = Mapping[str, Scalar]


class Severity(StrEnum):
    """Business impact assigned to a rule and its findings."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class RuleCategory(StrEnum):
    """Stable high-level classification for GIS quality rules."""

    ATTRIBUTE = "attribute"
    COMPLETENESS = "completeness"
    GEOMETRY = "geometry"
    METADATA = "metadata"
    TOPOLOGY = "topology"


class ResultStatus(StrEnum):
    """Execution outcome for a single rule."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class RuleFinding:
    """One actionable quality issue, optionally tied to a source feature."""

    message: str
    feature_id: str | int | None = None
    details: Metadata = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("Finding message must not be empty")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


@dataclass(frozen=True, slots=True)
class RuleResult:
    """Validated output returned by every rule execution."""

    rule_id: str
    status: ResultStatus
    findings: tuple[RuleFinding, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("Result rule_id must not be empty")
        if self.status is ResultStatus.PASSED and self.findings:
            raise ValueError("A passed result cannot contain findings")
        if self.status is ResultStatus.FAILED and not self.findings:
            raise ValueError("A failed result must contain at least one finding")
        if self.status is ResultStatus.ERROR and not self.error:
            raise ValueError("An error result must include an error message")
        if self.status is not ResultStatus.ERROR and self.error is not None:
            raise ValueError("Only an error result can include an error message")

    @classmethod
    def passed(cls, rule_id: str) -> "RuleResult":
        """Build a successful result without findings."""
        return cls(rule_id=rule_id, status=ResultStatus.PASSED)

    @classmethod
    def failed(cls, rule_id: str, *findings: RuleFinding) -> "RuleResult":
        """Build a failed quality check from one or more findings."""
        return cls(rule_id=rule_id, status=ResultStatus.FAILED, findings=tuple(findings))

    @classmethod
    def errored(cls, rule_id: str, error: str) -> "RuleResult":
        """Build an operational error result."""
        return cls(rule_id=rule_id, status=ResultStatus.ERROR, error=error)


@dataclass(frozen=True, slots=True)
class EngineResult:
    """Deterministic aggregate returned after executing selected rules."""

    results: tuple[RuleResult, ...]

    @property
    def has_failures(self) -> bool:
        """Return whether any quality failure or execution error occurred."""
        return any(result.status is not ResultStatus.PASSED for result in self.results)
