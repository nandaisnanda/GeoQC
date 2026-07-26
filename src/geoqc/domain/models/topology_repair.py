"""Framework-independent models for intelligent topology repair.

Geometries are carried as WKT strings so the domain and application layers stay
free of any GIS library; only the infrastructure adapter touches Shapely. The
before/after WKT pair on every result is the audit trail that makes a repair
reversible and reportable.
"""

from dataclasses import dataclass
from enum import StrEnum


class RepairMode(StrEnum):
    """Whether a repair is computed only, or committed to the working set."""

    PREVIEW = "preview"
    APPLY = "apply"


class RepairIssueType(StrEnum):
    """Stable categories of topology problems that can be repaired."""

    SELF_INTERSECTION = "self_intersection"
    DUPLICATE_VERTEX = "duplicate_vertex"
    INVALID_RING = "invalid_ring"
    SLIVER_POLYGON = "sliver_polygon"
    OVERLAP = "overlap"
    GAP = "gap"


class RepairStatus(StrEnum):
    """Outcome of a single geometry (or feature) repair attempt."""

    REPAIRED = "repaired"
    UNCHANGED = "unchanged"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RepairConfig:
    """Tunable, unit-aware thresholds controlling repair aggressiveness.

    All area thresholds are expressed in the geometry's own coordinate units
    squared; callers working in degrees must scale accordingly. Defaults are
    intentionally small so only degenerate artifacts are removed.
    """

    remove_duplicate_vertices: bool = True
    duplicate_vertex_tolerance: float = 0.0
    fix_invalid: bool = True
    remove_slivers: bool = True
    sliver_area_threshold: float = 1e-9
    sliver_thinness_threshold: float = 1e-3
    resolve_overlaps: bool = True
    fill_gaps: bool = True
    gap_area_threshold: float = 1e-6
    max_shape_shift: float | None = None
    max_relative_area_change: float | None = None

    def __post_init__(self) -> None:
        for name in (
            "sliver_area_threshold",
            "sliver_thinness_threshold",
            "gap_area_threshold",
            "duplicate_vertex_tolerance",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        for name in ("max_shape_shift", "max_relative_area_change"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative when provided")


@dataclass(frozen=True, slots=True)
class RepairAction:
    """One repair step applied to a geometry, for the audit trail."""

    issue_type: RepairIssueType
    strategy: str
    detail: str


@dataclass(frozen=True, slots=True)
class RepairMetrics:
    """Quantified difference between the original and repaired geometry."""

    area_before: float
    area_after: float
    vertex_count_before: int
    vertex_count_after: int
    shape_shift: float

    @property
    def area_delta(self) -> float:
        """Signed change in area (negative means area was removed)."""
        return self.area_after - self.area_before

    @property
    def vertex_delta(self) -> int:
        """Signed change in vertex count."""
        return self.vertex_count_after - self.vertex_count_before


@dataclass(frozen=True, slots=True)
class GeometryRepairResult:
    """Complete, reversible outcome for repairing one geometry."""

    geometry_type: str
    status: RepairStatus
    before_wkt: str
    after_wkt: str
    actions: tuple[RepairAction, ...]
    metrics: RepairMetrics
    failure_reason: str | None = None

    @property
    def is_changed(self) -> bool:
        """Return whether the repaired geometry differs from the original."""
        return self.status is RepairStatus.REPAIRED and self.before_wkt != self.after_wkt

    def has_action(self, issue_type: RepairIssueType) -> bool:
        """Return whether a particular repair category was applied."""
        return any(action.issue_type is issue_type for action in self.actions)


@dataclass(frozen=True, slots=True)
class FeatureRepairResult:
    """One geometry's repair result, tagged with its position in a dataset."""

    feature_index: int
    result: GeometryRepairResult


@dataclass(frozen=True, slots=True)
class RepairReport:
    """Aggregate, serializable summary over a set of geometry repairs."""

    results: tuple[FeatureRepairResult, ...]

    @property
    def total(self) -> int:
        """Number of geometries considered."""
        return len(self.results)

    @property
    def repaired_count(self) -> int:
        """Number of geometries that were changed by repair."""
        return sum(1 for item in self.results if item.result.is_changed)

    @property
    def unchanged_count(self) -> int:
        """Number of geometries that needed no repair."""
        return sum(1 for item in self.results if item.result.status is RepairStatus.UNCHANGED)

    @property
    def failed_count(self) -> int:
        """Number of geometries that could not be repaired safely."""
        return sum(1 for item in self.results if item.result.status is RepairStatus.FAILED)

    @property
    def action_counts(self) -> dict[str, int]:
        """Count of applied repair actions grouped by issue type."""
        counts: dict[str, int] = {}
        for item in self.results:
            for action in item.result.actions:
                key = str(action.issue_type.value)
                counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def total_area_delta(self) -> float:
        """Sum of signed area changes across all repairs."""
        return sum(item.result.metrics.area_delta for item in self.results)

    @property
    def max_shape_shift(self) -> float:
        """Largest single-geometry shape displacement (Hausdorff distance)."""
        return max((item.result.metrics.shape_shift for item in self.results), default=0.0)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable summary of the report."""
        return {
            "total": self.total,
            "repaired": self.repaired_count,
            "unchanged": self.unchanged_count,
            "failed": self.failed_count,
            "action_counts": self.action_counts,
            "total_area_delta": self.total_area_delta,
            "max_shape_shift": self.max_shape_shift,
            "features": [
                {
                    "feature_index": item.feature_index,
                    "status": str(item.result.status.value),
                    "geometry_type": item.result.geometry_type,
                    "actions": [
                        {
                            "issue_type": str(action.issue_type.value),
                            "strategy": action.strategy,
                            "detail": action.detail,
                        }
                        for action in item.result.actions
                    ],
                    "area_before": item.result.metrics.area_before,
                    "area_after": item.result.metrics.area_after,
                    "vertex_delta": item.result.metrics.vertex_delta,
                    "shape_shift": item.result.metrics.shape_shift,
                    "before_wkt": item.result.before_wkt,
                    "after_wkt": item.result.after_wkt,
                    "failure_reason": item.result.failure_reason,
                }
                for item in self.results
            ],
        }


@dataclass(frozen=True, slots=True)
class CoverageRepairResult:
    """Result of repairing a set of geometries as one topological coverage."""

    before_wkt: tuple[str, ...]
    after_wkt: tuple[str, ...]
    report: RepairReport
