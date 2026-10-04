"""Framework-neutral topology, finding, and repair-plan values."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from types import MappingProxyType

from geoqc.domain.rules.models import Severity


class RepairRisk(StrEnum):
    """Human-review requirement for a proposed repair."""

    SAFE = "safe"
    REVIEW = "review"
    DANGEROUS = "dangerous"
    NOT_REPAIRABLE = "not_repairable"


class IssueGeometryKind(StrEnum):
    POINT = "point"
    LINE = "line"
    POLYGON = "polygon"


class TopologyRuleType(StrEnum):
    """Cross-feature and cross-layer constraints understood by GeoQC."""

    NO_OVERLAP = "no_overlap"
    NO_GAP = "no_gap"
    NO_DUPLICATE = "no_duplicate"
    MUST_BE_INSIDE = "must_be_inside"
    MUST_NOT_INTERSECT = "must_not_intersect"
    MINIMUM_AREA = "minimum_area"
    BOUNDARY_MUST_MATCH = "boundary_must_match"
    NO_DANGLES = "no_dangles"
    ENDPOINT_MUST_CONNECT = "endpoint_must_connect"
    NO_OVERSHOOT_UNDERSHOOT = "no_overshoot_undershoot"
    ALLOWED_GEOMETRY_TYPE = "allowed_geometry_type"
    SINGLEPART_ONLY = "singlepart_only"
    NO_SPIKES = "no_spikes"
    MINIMUM_SEGMENT_LENGTH = "minimum_segment_length"
    MINIMUM_VERTEX_DISTANCE = "minimum_vertex_distance"
    MUST_TOUCH = "must_touch"
    MUST_INTERSECT = "must_intersect"
    MUST_COVER = "must_cover"
    ATTRIBUTE_OVERLAP = "attribute_overlap"
    PRECISION_GRID = "precision_grid"


class AttributeOverlapPolicy(StrEnum):
    """Decide which overlapping feature pairs are permitted by an attribute."""

    DENY_ALL = "deny_all"
    ALLOW_EQUAL = "allow_equal"
    ALLOW_DIFFERENT = "allow_different"


class AttributeRuleType(StrEnum):
    REQUIRED = "required"
    NOT_NULL = "not_null"
    UNIQUE = "unique"
    ALLOWED_VALUES = "allowed_values"
    NUMERIC_RANGE = "numeric_range"


@dataclass(frozen=True, slots=True)
class AttributeRule:
    column: str
    rule_type: AttributeRuleType
    severity: Severity = Severity.ERROR
    allowed_values: tuple[str | int | float | bool, ...] = ()
    minimum: float | None = None
    maximum: float | None = None

    def __post_init__(self) -> None:
        if not self.column.strip():
            raise ValueError("attribute rule column must not be empty")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("attribute rule minimum must not exceed maximum")
        if self.rule_type is AttributeRuleType.ALLOWED_VALUES and not self.allowed_values:
            raise ValueError("allowed_values rule requires at least one value")


@dataclass(frozen=True, slots=True)
class TopologyRule:
    rule_type: TopologyRuleType
    layer: str
    reference_layer: str | None = None
    tolerance: float = 0.0
    minimum_area: float = 0.0
    minimum_length: float = 0.0
    minimum_distance: float = 0.0
    minimum_angle: float = 0.0
    allowed_geometry_types: tuple[str, ...] = ()
    precision_grid_size: float = 0.0
    attribute_column: str | None = None
    overlap_policy: AttributeOverlapPolicy = AttributeOverlapPolicy.DENY_ALL
    severity: Severity = Severity.ERROR

    def __post_init__(self) -> None:
        thresholds = (
            self.tolerance,
            self.minimum_area,
            self.minimum_length,
            self.minimum_distance,
            self.minimum_angle,
            self.precision_grid_size,
        )
        if not self.layer.strip():
            raise ValueError("layer must not be empty")
        if any(value < 0 for value in thresholds):
            raise ValueError("rule thresholds must be non-negative")
        if self.minimum_angle > 180:
            raise ValueError("minimum_angle must not exceed 180 degrees")
        needs_reference = self.rule_type in {
            TopologyRuleType.MUST_BE_INSIDE,
            TopologyRuleType.MUST_NOT_INTERSECT,
            TopologyRuleType.BOUNDARY_MUST_MATCH,
            TopologyRuleType.MUST_TOUCH,
            TopologyRuleType.MUST_INTERSECT,
            TopologyRuleType.MUST_COVER,
        }
        if needs_reference and not self.reference_layer:
            raise ValueError(f"{self.rule_type.value} requires reference_layer")
        if (
            self.rule_type is TopologyRuleType.ALLOWED_GEOMETRY_TYPE
            and not self.allowed_geometry_types
        ):
            raise ValueError("allowed_geometry_type requires allowed_geometry_types")
        if self.rule_type is TopologyRuleType.NO_SPIKES and self.minimum_angle <= 0:
            raise ValueError("no_spikes requires a positive minimum_angle")
        if self.rule_type is TopologyRuleType.MINIMUM_SEGMENT_LENGTH and self.minimum_length <= 0:
            raise ValueError("minimum_segment_length requires a positive minimum_length")
        if (
            self.rule_type is TopologyRuleType.MINIMUM_VERTEX_DISTANCE
            and self.minimum_distance <= 0
        ):
            raise ValueError("minimum_vertex_distance requires a positive minimum_distance")
        if self.rule_type is TopologyRuleType.PRECISION_GRID and self.precision_grid_size <= 0:
            raise ValueError("precision_grid requires a positive precision_grid_size")
        if self.rule_type is TopologyRuleType.ATTRIBUTE_OVERLAP and (
            self.attribute_column is None or not self.attribute_column.strip()
        ):
            raise ValueError("attribute_overlap requires attribute_column")


@dataclass(frozen=True, slots=True)
class DatasetLayer:
    """Framework-neutral layer input for custom topology rules."""

    name: str
    geometries_wkt: tuple[str, ...]
    crs: str | None = None
    attributes: tuple[Mapping[str, str | int | float | bool | None], ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("layer name must not be empty")
        if self.attributes and len(self.attributes) != len(self.geometries_wkt):
            raise ValueError("attributes must contain one mapping per geometry")
        object.__setattr__(
            self,
            "attributes",
            tuple(MappingProxyType(dict(item)) for item in self.attributes),
        )


@dataclass(frozen=True, slots=True)
class DatasetIssue:
    """One actionable finding, including geometry suitable for an issue layer."""

    code: str
    issue_type: str
    title: str
    message: str
    severity: Severity
    category: str
    recommendation: str
    repair_risk: RepairRisk
    geometry_kind: IssueGeometryKind
    geometry_wkt: str
    layer: str | None = None
    feature_index: int | None = None
    related_feature_index: int | None = None
    feature_id: str | int | None = None
    related_feature_id: str | int | None = None
    metadata: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)
    check_name: str | None = None

    def __post_init__(self) -> None:
        for name in ("code", "issue_type", "title", "message", "category", "recommendation"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        if not self.geometry_wkt.strip():
            raise ValueError("geometry_wkt must not be empty")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def fingerprint(self) -> str:
        primary = (
            f"id:{self.feature_id}"
            if self.feature_id is not None
            else f"index:{self.feature_index}:geometry:{self.geometry_wkt}"
        )
        related = (
            f"id:{self.related_feature_id}"
            if self.related_feature_id is not None
            else (
                f"index:{self.related_feature_index}"
                if self.related_feature_index is not None
                else ""
            )
        )
        entities = "\x1e".join(sorted((primary, related))) if related else primary
        identity = "\x1f".join((self.issue_type, self.layer or "", entities))
        return sha256(identity.encode("utf-8")).hexdigest()[:24]

    def to_dict(self) -> dict[str, object]:
        return {
            "fingerprint": self.fingerprint,
            "check_name": self.check_name or self.category,
            "code": self.code,
            "issue_type": self.issue_type,
            "title": self.title,
            "message": self.message,
            "severity": self.severity.value,
            "category": self.category,
            "recommendation": self.recommendation,
            "repair_risk": self.repair_risk.value,
            "geometry_kind": self.geometry_kind.value,
            "geometry_wkt": self.geometry_wkt,
            "layer": self.layer,
            "feature_index": self.feature_index,
            "related_feature_index": self.related_feature_index,
            "feature_id": self.feature_id,
            "related_feature_id": self.related_feature_id,
            "metadata": dict(self.metadata),
        }

    @property
    def feature_indices(self) -> tuple[int, ...]:
        return tuple(
            sorted(
                index
                for index in (self.feature_index, self.related_feature_index)
                if index is not None
            )
        )


@dataclass(frozen=True, slots=True)
class RepairPlanAction:
    issue_fingerprint: str
    feature_index: int | None
    issue_type: str
    strategy: str
    risk: RepairRisk
    automatic: bool


@dataclass(frozen=True, slots=True)
class RepairPlanConflict:
    feature_index: int | None
    issue_fingerprints: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class RepairPlan:
    actions: tuple[RepairPlanAction, ...]
    conflicts: tuple[RepairPlanConflict, ...] = ()

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)

    @property
    def automatic_actions(self) -> tuple[RepairPlanAction, ...]:
        return tuple(item for item in self.actions if item.automatic)
