"""Framework-free models for enterprise spatial analysis workflows."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any


def _unit(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between zero and one")


def _positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class DuplicateWeights:
    """Weights used to combine IoU, Hausdorff, and shape similarity."""

    iou: float = 0.45
    hausdorff: float = 0.35
    shape: float = 0.20

    def __post_init__(self) -> None:
        for name in ("iou", "hausdorff", "shape"):
            _unit(name, getattr(self, name))
        if abs(self.iou + self.hausdorff + self.shape - 1.0) > 1e-9:
            raise ValueError("duplicate weights must sum to one")


@dataclass(frozen=True, slots=True)
class SpatialDuplicateConfig:
    similarity_threshold: float = 0.85
    search_tolerance: float = 0.0
    maximum_pairs: int = 100_000
    weights: DuplicateWeights = field(default_factory=DuplicateWeights)

    def __post_init__(self) -> None:
        _unit("similarity_threshold", self.similarity_threshold)
        if self.search_tolerance < 0:
            raise ValueError("search_tolerance must be non-negative")
        if self.maximum_pairs < 1:
            raise ValueError("maximum_pairs must be positive")


@dataclass(frozen=True, slots=True)
class DuplicatePair:
    left_index: int
    right_index: int
    similarity_percent: float
    iou: float
    hausdorff_similarity: float
    shape_similarity: float
    exact: bool
    left_wkt: str
    right_wkt: str


@dataclass(frozen=True, slots=True)
class SpatialDuplicateReport:
    feature_count: int
    possible_pairs: int
    candidate_pairs: int
    evaluated_pairs: int
    pairs: tuple[DuplicatePair, ...]
    truncated: bool = False

    @property
    def duplicate_count(self) -> int:
        return len(self.pairs)

    @property
    def candidate_reduction_percent(self) -> float:
        if self.possible_pairs == 0:
            return 100.0
        return 100.0 * (1.0 - self.candidate_pairs / self.possible_pairs)


@dataclass(frozen=True, slots=True)
class DatasetSnapshot:
    """Portable dataset representation used by the comparison engine."""

    geometries_wkt: tuple[str, ...]
    attributes: tuple[Mapping[str, Any], ...] = ()
    crs: str | None = None
    schema: Mapping[str, str] = field(default_factory=dict)
    name: str = "dataset"

    def __post_init__(self) -> None:
        if self.attributes and len(self.attributes) != len(self.geometries_wkt):
            raise ValueError("attributes must be empty or match geometry count")
        object.__setattr__(self, "schema", MappingProxyType(dict(self.schema)))
        object.__setattr__(
            self,
            "attributes",
            tuple(MappingProxyType(dict(item)) for item in self.attributes),
        )


class DifferenceKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class FeatureDifference:
    kind: DifferenceKind
    left_index: int | None
    right_index: int | None
    geometry_similarity_percent: float
    changed_attributes: tuple[str, ...] = ()
    left_wkt: str | None = None
    right_wkt: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetDifferenceReport:
    left_name: str
    right_name: str
    crs_equal: bool
    left_crs: str | None
    right_crs: str | None
    schema_added: tuple[str, ...]
    schema_removed: tuple[str, ...]
    schema_changed: tuple[str, ...]
    boundary_iou: float
    boundary_difference_area: float
    differences: tuple[FeatureDifference, ...]
    candidate_pairs: int
    warnings: tuple[str, ...] = ()

    def count(self, kind: DifferenceKind) -> int:
        return sum(item.kind is kind for item in self.differences)


class ConflictType(StrEnum):
    ROAD_RIVER_CROSSING = "road_river_crossing"
    BUILDING_IN_RIVER = "building_in_river"
    INTER_AGENCY_OVERLAP = "inter_agency_overlap"
    BOUNDARY_CONFLICT = "boundary_conflict"


@dataclass(frozen=True, slots=True)
class ConflictPolicy:
    road_river_base: float = 45.0
    building_river_base: float = 80.0
    overlap_base: float = 60.0
    boundary_base: float = 55.0
    magnitude_weight: float = 20.0

    def __post_init__(self) -> None:
        for name in (
            "road_river_base",
            "building_river_base",
            "overlap_base",
            "boundary_base",
            "magnitude_weight",
        ):
            if not 0 <= getattr(self, name) <= 100:
                raise ValueError(f"{name} must be between zero and 100")


@dataclass(frozen=True, slots=True)
class SpatialLayer:
    name: str
    role: str
    geometries_wkt: tuple[str, ...]
    agency: str | None = None


@dataclass(frozen=True, slots=True)
class SpatialConflict:
    conflict_type: ConflictType
    left_layer: str
    right_layer: str
    left_index: int
    right_index: int
    severity_score: float
    magnitude: float
    message: str
    geometry_wkt: str


@dataclass(frozen=True, slots=True)
class SpatialConflictReport:
    conflicts: tuple[SpatialConflict, ...]
    candidate_pairs: int

    @property
    def maximum_severity(self) -> float:
        return max((item.severity_score for item in self.conflicts), default=0.0)


@dataclass(frozen=True, slots=True)
class PriorityWeights:
    severity: float = 0.40
    impact: float = 0.30
    area: float = 0.15
    feature_count: float = 0.15

    def __post_init__(self) -> None:
        for name in ("severity", "impact", "area", "feature_count"):
            _unit(name, getattr(self, name))
        if abs(sum((self.severity, self.impact, self.area, self.feature_count)) - 1) > 1e-9:
            raise ValueError("priority weights must sum to one")


@dataclass(frozen=True, slots=True)
class RepairCandidate:
    issue_id: str
    issue_type: str
    severity: float
    impact: float
    area: float
    feature_count: int
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("severity", "impact"):
            if not 0 <= getattr(self, name) <= 100:
                raise ValueError(f"{name} must be between zero and 100")
        if self.area < 0 or self.feature_count < 0:
            raise ValueError("area and feature_count must be non-negative")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class RepairRecommendation:
    rank: int
    issue_id: str
    priority_score: float
    action: str
    rationale: str
