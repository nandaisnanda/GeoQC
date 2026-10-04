"""Framework-neutral CRS and quality scoring values."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from geoqc.domain.rules.models import Severity


class CrsUnitStatus(StrEnum):
    SAFE = "safe"
    WARNING = "warning"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CrsGuardResult:
    crs: str | None
    status: CrsUnitStatus
    unit_name: str | None
    uses_angular_units: bool
    message: str
    suggested_projected_crs: str | None = None


@dataclass(frozen=True, slots=True)
class CategoryScore:
    category: str
    score: float
    issue_count: int


@dataclass(frozen=True, slots=True)
class ScoreDeduction:
    category: str
    issue_fingerprint: str
    severity: Severity
    points: float
    explanation: str


@dataclass(frozen=True, slots=True)
class ScoringPolicy:
    """Size-normalized scoring inputs with bounded repeated deductions."""

    category_weights: Mapping[str, float] = field(
        default_factory=lambda: {
            "geometry": 0.35,
            "topology": 0.35,
            "network": 0.20,
            "attribute": 0.05,
            "metadata": 0.05,
        }
    )
    severity_penalties: Mapping[Severity, float] = field(
        default_factory=lambda: {
            Severity.INFO: 1.0,
            Severity.WARNING: 5.0,
            Severity.ERROR: 10.0,
            Severity.CRITICAL: 25.0,
        }
    )
    category_caps: Mapping[str, float] = field(default_factory=dict)
    repeated_feature_cap: float = 30.0

    def __post_init__(self) -> None:
        weights = dict(self.category_weights)
        penalties = {Severity(key): value for key, value in self.severity_penalties.items()}
        caps = dict(self.category_caps) or {category: 80.0 for category in weights}
        if not weights or any(value < 0 for value in weights.values()):
            raise ValueError("category weights must be non-negative and non-empty")
        if sum(weights.values()) <= 0:
            raise ValueError("at least one category weight must be positive")
        if set(penalties) != set(Severity) or any(value < 0 for value in penalties.values()):
            raise ValueError("severity penalties must define every severity as non-negative")
        if set(caps) != set(weights) or any(not 0 <= value <= 100 for value in caps.values()):
            raise ValueError("category caps must define every category between zero and 100")
        if not 0 <= self.repeated_feature_cap <= 100:
            raise ValueError("repeated_feature_cap must be between zero and 100")
        object.__setattr__(self, "category_weights", MappingProxyType(weights))
        object.__setattr__(self, "severity_penalties", MappingProxyType(penalties))
        object.__setattr__(self, "category_caps", MappingProxyType(caps))
