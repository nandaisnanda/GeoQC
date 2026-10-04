"""Versioned, framework-neutral quality profile values."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from geoqc.domain.models.scoring import ScoringPolicy
from geoqc.domain.models.topology import AttributeRule, TopologyRule
from geoqc.domain.rules.models import Severity


class QualityPreset(StrEnum):
    """Opinionated rule bundles for common GIS datasets."""

    PARCEL = "parcel"
    ROAD = "road"
    ADMIN_BOUNDARY = "admin_boundary"
    POINT_SURVEY = "point_survey"


@dataclass(frozen=True, slots=True)
class QualityGatePolicy:
    """CI policy used to turn an audit into a deterministic pass/fail decision."""

    minimum_score: float = 75.0
    fail_on: Severity = Severity.ERROR
    allow_unknown_crs: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.minimum_score <= 100:
            raise ValueError("minimum_score must be between zero and 100")


@dataclass(frozen=True, slots=True)
class QualityProfile:
    """Shareable, versioned configuration for a complete QC run."""

    name: str
    version: int = 1
    preset: QualityPreset | None = None
    tolerance: float = 0.0
    minimum_area: float = 0.0
    require_crs: bool = True
    require_projected_crs: bool = False
    allowed_crs: tuple[str, ...] = ()
    id_column: str | None = None
    enabled_checks: tuple[str, ...] = ("geometry", "crs", "attributes", "topology", "spatial")
    expected_geometry_types: tuple[str, ...] = ()
    topology_rules: tuple[TopologyRule, ...] = ()
    attribute_rules: tuple[AttributeRule, ...] = ()
    severity_overrides: Mapping[str, Severity] = field(default_factory=dict)
    scoring: ScoringPolicy = field(default_factory=ScoringPolicy)
    gate: QualityGatePolicy = field(default_factory=QualityGatePolicy)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("profile name must not be empty")
        if self.version < 1:
            raise ValueError("profile version must be positive")
        if self.tolerance < 0 or self.minimum_area < 0:
            raise ValueError("profile thresholds must be non-negative")
        if self.id_column is not None and not self.id_column.strip():
            raise ValueError("id_column must not be empty when provided")
        supported = {"geometry", "crs", "attributes", "topology", "spatial"}
        unknown = set(self.enabled_checks) - supported
        if not self.enabled_checks or unknown:
            raise ValueError(f"enabled_checks contains unsupported values: {sorted(unknown)}")
        if any(not item.strip() for item in self.expected_geometry_types):
            raise ValueError("expected_geometry_types must not contain empty values")
        object.__setattr__(
            self,
            "severity_overrides",
            MappingProxyType(
                {str(key): Severity(value) for key, value in self.severity_overrides.items()}
            ),
        )
