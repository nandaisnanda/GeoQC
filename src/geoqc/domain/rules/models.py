"""Immutable value objects shared by rules and the rule engine."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from types import MappingProxyType

_IDENT = r"(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
_SEMVER = re.compile(
    r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    rf"(?:-{_IDENT}(?:\.{_IDENT})*)?"
    r"(?:\+[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*)?"
)
DEFAULT_RULE_VERSION = "1.0.0"

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


class FindingKind(StrEnum):
    """How a finding was established, so readers can weigh its certainty."""

    RULE_VIOLATION = "rule_violation"
    STATISTICAL_ANOMALY = "statistical_anomaly"
    AI_SUSPICION = "ai_suspicion"
    CONTEXTUAL_INCONSISTENCY = "contextual_inconsistency"
    CONFIRMED_ERROR = "confirmed_error"


class ProvenanceOrigin(StrEnum):
    """Where a rule definition comes from."""

    BUILT_IN = "built-in"
    PRESET = "preset"
    PROFILE = "profile"


class ResultStatus(StrEnum):
    """Execution outcome for a single rule."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


def is_semver(value: str) -> bool:
    """Return whether ``value`` is a valid Semantic Versioning 2.0.0 string."""
    return _SEMVER.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class Tolerance:
    """Numeric threshold a rule applies, always paired with its unit."""

    value: float
    unit: str

    def __post_init__(self) -> None:
        if not isfinite(self.value) or self.value < 0:
            raise ValueError("Tolerance value must be finite and non-negative")
        if not self.unit.strip():
            raise ValueError("Tolerance unit must not be empty")


@dataclass(frozen=True, slots=True)
class Provenance:
    """Origin of a rule definition and the source that justifies it."""

    origin: ProvenanceOrigin
    source: str

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("Provenance source must not be empty")


BUILT_IN_PROVENANCE = Provenance(ProvenanceOrigin.BUILT_IN, "geoqc")


@dataclass(frozen=True, slots=True)
class RuleMetadata:
    """Versioned, auditable description of one rule, kept apart from ``Rule``."""

    rule_id: str
    severity: Severity
    version: str = DEFAULT_RULE_VERSION
    tolerance: Tolerance | None = None
    provenance: Provenance = BUILT_IN_PROVENANCE

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("Metadata rule_id must not be empty")
        if not is_semver(self.version):
            raise ValueError(f"Rule version {self.version!r} is not a valid semver string")


@dataclass(frozen=True, slots=True)
class RuleFinding:
    """One actionable quality issue, optionally tied to a source feature."""

    message: str
    feature_id: str | int | None = None
    details: Metadata = field(default_factory=dict)
    kind: FindingKind = FindingKind.RULE_VIOLATION

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
