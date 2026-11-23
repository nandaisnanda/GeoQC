"""Public contracts for defining and executing GeoQC rules."""

from geoqc.domain.rules.base import Rule
from geoqc.domain.rules.engine import ErrorPolicy, RuleEngine
from geoqc.domain.rules.models import (
    EngineResult,
    FindingKind,
    Metadata,
    Provenance,
    ProvenanceOrigin,
    ResultStatus,
    RuleCategory,
    RuleFinding,
    RuleMetadata,
    RuleResult,
    Severity,
    Tolerance,
)
from geoqc.domain.rules.registry import RuleRegistry

__all__ = [
    "EngineResult",
    "ErrorPolicy",
    "FindingKind",
    "Metadata",
    "Provenance",
    "ProvenanceOrigin",
    "ResultStatus",
    "Rule",
    "RuleCategory",
    "RuleEngine",
    "RuleFinding",
    "RuleMetadata",
    "RuleRegistry",
    "RuleResult",
    "Severity",
    "Tolerance",
]
