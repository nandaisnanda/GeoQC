"""Public contracts for defining and executing GeoQC rules."""

from geoqc.domain.rules.base import Rule
from geoqc.domain.rules.engine import ErrorPolicy, RuleEngine
from geoqc.domain.rules.models import (
    EngineResult,
    Metadata,
    ResultStatus,
    RuleCategory,
    RuleFinding,
    RuleResult,
    Severity,
)
from geoqc.domain.rules.registry import RuleRegistry

__all__ = [
    "EngineResult",
    "ErrorPolicy",
    "Metadata",
    "ResultStatus",
    "Rule",
    "RuleCategory",
    "RuleEngine",
    "RuleFinding",
    "RuleRegistry",
    "RuleResult",
    "Severity",
]
