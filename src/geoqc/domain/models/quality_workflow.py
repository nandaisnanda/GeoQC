"""Portable models for end-to-end dataset quality-control workflows."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from types import MappingProxyType

from geoqc.domain.rules.models import Severity


class QualityPreset(StrEnum):
    """Opinionated rule bundles for common GIS datasets."""

    PARCEL = "parcel"
    ROAD = "road"
    ADMIN_BOUNDARY = "admin_boundary"
    POINT_SURVEY = "point_survey"


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


class CrsUnitStatus(StrEnum):
    SAFE = "safe"
    WARNING = "warning"
    UNKNOWN = "unknown"


class TopologyRuleType(StrEnum):
    """Cross-feature and cross-layer constraints understood by GeoQC."""

    NO_OVERLAP = "no_overlap"
    NO_GAP = "no_gap"
    NO_DUPLICATE = "no_duplicate"
    MUST_BE_INSIDE = "must_be_inside"
    MUST_NOT_INTERSECT = "must_not_intersect"
    MINIMUM_AREA = "minimum_area"


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
    severity: Severity = Severity.ERROR

    def __post_init__(self) -> None:
        if not self.layer.strip():
            raise ValueError("layer must not be empty")
        if self.tolerance < 0 or self.minimum_area < 0:
            raise ValueError("rule thresholds must be non-negative")
        needs_reference = self.rule_type in {
            TopologyRuleType.MUST_BE_INSIDE,
            TopologyRuleType.MUST_NOT_INTERSECT,
        }
        if needs_reference and not self.reference_layer:
            raise ValueError(f"{self.rule_type.value} requires reference_layer")


@dataclass(frozen=True, slots=True)
class DatasetLayer:
    """Framework-neutral layer input for custom topology rules."""

    name: str
    geometries_wkt: tuple[str, ...]
    crs: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("layer name must not be empty")


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

    def __post_init__(self) -> None:
        for name in ("code", "issue_type", "title", "message", "category", "recommendation"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        if not self.geometry_wkt.strip():
            raise ValueError("geometry_wkt must not be empty")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def fingerprint(self) -> str:
        """Return a stable identity independent from wording and severity changes."""
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
        identity = "\x1f".join(
            (
                self.issue_type,
                self.layer or "",
                entities,
            )
        )
        return sha256(identity.encode("utf-8")).hexdigest()[:24]


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
    """Configurable category weights and per-issue severity penalties."""

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

    def __post_init__(self) -> None:
        weights = dict(self.category_weights)
        penalties = {Severity(key): value for key, value in self.severity_penalties.items()}
        if not weights or any(value < 0 for value in weights.values()):
            raise ValueError("category weights must be non-negative and non-empty")
        if sum(weights.values()) <= 0:
            raise ValueError("at least one category weight must be positive")
        if set(penalties) != set(Severity) or any(value < 0 for value in penalties.values()):
            raise ValueError("severity penalties must define every severity as non-negative")
        object.__setattr__(self, "category_weights", MappingProxyType(weights))
        object.__setattr__(self, "severity_penalties", MappingProxyType(penalties))


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
    topology_rules: tuple[TopologyRule, ...] = ()
    attribute_rules: tuple[AttributeRule, ...] = ()
    scoring: ScoringPolicy = field(default_factory=ScoringPolicy)
    gate: "QualityGatePolicy" = field(default_factory=lambda: QualityGatePolicy())

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("profile name must not be empty")
        if self.version < 1:
            raise ValueError("profile version must be positive")
        if self.tolerance < 0 or self.minimum_area < 0:
            raise ValueError("profile thresholds must be non-negative")
        if self.id_column is not None and not self.id_column.strip():
            raise ValueError("id_column must not be empty when provided")


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
class DatasetAuditResult:
    dataset_name: str
    preset: QualityPreset | None
    feature_count: int
    issues: tuple[DatasetIssue, ...]
    crs_guard: CrsGuardResult
    category_scores: tuple[CategoryScore, ...]
    quality_score: float
    score_deductions: tuple[ScoreDeduction, ...] = ()
    profile_name: str | None = None
    schema_version: str = "1.0"

    @property
    def is_clean(self) -> bool:
        return not self.issues

    def issues_for_layer(self, kind: IssueGeometryKind | str) -> tuple[DatasetIssue, ...]:
        """Return findings for one point/line/polygon issue layer."""
        normalized = IssueGeometryKind(kind)
        return tuple(issue for issue in self.issues if issue.geometry_kind is normalized)

    def passes(self, policy: QualityGatePolicy | None = None) -> bool:
        """Evaluate this result against a CI quality gate."""
        selected = policy or QualityGatePolicy()
        if self.quality_score < selected.minimum_score:
            return False
        if self.crs_guard.status is CrsUnitStatus.UNKNOWN and not selected.allow_unknown_crs:
            return False
        ranks = {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2, Severity.CRITICAL: 3}
        threshold = ranks[selected.fail_on]
        return not any(ranks[issue.severity] >= threshold for issue in self.issues)

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-serializable representation for adapters."""
        return {
            "schema_version": self.schema_version,
            "dataset_name": self.dataset_name,
            "profile_name": self.profile_name,
            "preset": self.preset.value if self.preset else None,
            "feature_count": self.feature_count,
            "quality_score": self.quality_score,
            "is_clean": self.is_clean,
            "crs": {
                "value": self.crs_guard.crs,
                "status": self.crs_guard.status.value,
                "unit_name": self.crs_guard.unit_name,
                "uses_angular_units": self.crs_guard.uses_angular_units,
                "message": self.crs_guard.message,
                "suggested_projected_crs": self.crs_guard.suggested_projected_crs,
            },
            "category_scores": [
                {"category": item.category, "score": item.score, "issue_count": item.issue_count}
                for item in self.category_scores
            ],
            "score_deductions": [
                {
                    "category": item.category,
                    "issue_fingerprint": item.issue_fingerprint,
                    "severity": item.severity.value,
                    "points": item.points,
                    "explanation": item.explanation,
                }
                for item in self.score_deductions
            ],
            "issues": [
                {
                    "fingerprint": issue.fingerprint,
                    "code": issue.code,
                    "issue_type": issue.issue_type,
                    "title": issue.title,
                    "message": issue.message,
                    "severity": issue.severity.value,
                    "category": issue.category,
                    "recommendation": issue.recommendation,
                    "repair_risk": issue.repair_risk.value,
                    "geometry_kind": issue.geometry_kind.value,
                    "geometry_wkt": issue.geometry_wkt,
                    "layer": issue.layer,
                    "feature_index": issue.feature_index,
                    "related_feature_index": issue.related_feature_index,
                    "feature_id": issue.feature_id,
                    "related_feature_id": issue.related_feature_id,
                    "metadata": dict(issue.metadata),
                }
                for issue in self.issues
            ],
        }


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


@dataclass(frozen=True, slots=True)
class WorkflowArtifacts:
    result: DatasetAuditResult
    issue_dataset: str | None = None
    report: str | None = None
