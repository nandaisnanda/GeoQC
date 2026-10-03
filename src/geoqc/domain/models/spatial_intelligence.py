"""Framework-free models for spatial intelligence workflows."""

from dataclasses import dataclass
from enum import StrEnum


def _non_negative(name: str, value: float) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class BoundarySnapConfig:
    """Conservative boundary snapping policy in coordinate units."""

    tolerance: float = 0.01
    max_relative_area_change: float = 0.01
    max_shape_shift: float | None = None

    def __post_init__(self) -> None:
        if self.tolerance <= 0:
            raise ValueError("tolerance must be positive")
        _non_negative("max_relative_area_change", self.max_relative_area_change)
        if self.max_shape_shift is not None:
            _non_negative("max_shape_shift", self.max_shape_shift)


@dataclass(frozen=True, slots=True)
class BoundarySnapFeature:
    feature_index: int
    status: str
    before_wkt: str
    after_wkt: str
    area_before: float
    area_after: float
    shape_shift: float
    snapped_to: tuple[int, ...] = ()
    reason: str = ""

    @property
    def area_delta(self) -> float:
        return self.area_after - self.area_before


@dataclass(frozen=True, slots=True)
class BoundarySnapResult:
    features: tuple[BoundarySnapFeature, ...]
    candidate_pairs: int

    @property
    def repaired(self) -> int:
        return sum(item.status == "repaired" for item in self.features)

    @property
    def total_area_delta(self) -> float:
        return sum(item.area_delta for item in self.features)


class RoadIssueType(StrEnum):
    DANGLING_ROAD = "dangling_road"
    DEAD_END = "dead_end"
    BROKEN_CONNECTION = "broken_connection"
    DUPLICATE_SEGMENT = "duplicate_segment"
    LOOP_ERROR = "loop_error"
    UNNODED_INTERSECTION = "unnoded_intersection"


@dataclass(frozen=True, slots=True)
class RoadNetworkConfig:
    connection_tolerance: float = 0.01
    dangling_length_threshold: float = 1.0
    duplicate_tolerance: float = 1e-8
    duplicate_overlap_ratio: float = 0.98
    max_loop_length: float = 10.0

    def __post_init__(self) -> None:
        for name in (
            "connection_tolerance",
            "dangling_length_threshold",
            "duplicate_tolerance",
            "max_loop_length",
        ):
            _non_negative(name, getattr(self, name))
        if not 0 <= self.duplicate_overlap_ratio <= 1:
            raise ValueError("duplicate_overlap_ratio must be between zero and one")


@dataclass(frozen=True, slots=True)
class RoadFinding:
    issue_type: RoadIssueType
    feature_indices: tuple[int, ...]
    location_wkt: str
    message: str
    metric: float | None = None


@dataclass(frozen=True, slots=True)
class RoadNetworkReport:
    feature_count: int
    findings: tuple[RoadFinding, ...]

    @property
    def issue_counts(self) -> dict[str, int]:
        return {
            kind.value: sum(f.issue_type == kind for f in self.findings) for kind in RoadIssueType
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_count": self.feature_count,
            "issue_counts": self.issue_counts,
            "findings": [
                {
                    "issue_type": f.issue_type.value,
                    "feature_indices": list(f.feature_indices),
                    "location_wkt": f.location_wkt,
                    "message": f.message,
                    "metric": f.metric,
                }
                for f in self.findings
            ],
        }


@dataclass(frozen=True, slots=True)
class RoadNetworkRepairConfig:
    """Conservative settings for snapping and fully noding linework.

    ``snap_tolerance`` uses the input CRS coordinate unit. A value of zero
    disables endpoint snapping while intersection noding still runs.
    """

    snap_tolerance: float = 0.0
    minimum_segment_length: float = 1e-9

    def __post_init__(self) -> None:
        _non_negative("snap_tolerance", self.snap_tolerance)
        if self.minimum_segment_length <= 0:
            raise ValueError("minimum_segment_length must be positive")


@dataclass(frozen=True, slots=True)
class RoadRepairSegment:
    """One fully noded output segment and its input feature provenance."""

    segment_index: int
    source_indices: tuple[int, ...]
    geometry_wkt: str
    length: float


@dataclass(frozen=True, slots=True)
class RoadNetworkRepairResult:
    """Repaired road linework with an auditable source-to-segment mapping."""

    input_feature_count: int
    input_part_count: int
    snapped_endpoint_count: int
    segments: tuple[RoadRepairSegment, ...]

    @property
    def output_segment_count(self) -> int:
        return len(self.segments)

    def to_dict(self) -> dict[str, object]:
        return {
            "input_feature_count": self.input_feature_count,
            "input_part_count": self.input_part_count,
            "snapped_endpoint_count": self.snapped_endpoint_count,
            "output_segment_count": self.output_segment_count,
            "segments": [
                {
                    "segment_index": item.segment_index,
                    "source_indices": list(item.source_indices),
                    "geometry_wkt": item.geometry_wkt,
                    "length": item.length,
                }
                for item in self.segments
            ],
        }


class SmallPolygonIssueType(StrEnum):
    SLIVER_POLYGON = "sliver_polygon"
    TINY_ISLAND = "tiny_island"
    NOISE_GEOMETRY = "noise_geometry"


class Recommendation(StrEnum):
    DELETE = "delete"
    MERGE = "merge"
    IGNORE = "ignore"


@dataclass(frozen=True, slots=True)
class SmallPolygonConfig:
    sliver_area_threshold: float = 1.0
    sliver_compactness_threshold: float = 0.05
    tiny_island_area_threshold: float = 0.25
    isolation_distance: float = 1.0
    noise_area_threshold: float = 0.01
    merge_tolerance: float = 0.1
    max_target_area_change: float = 0.25

    def __post_init__(self) -> None:
        for name in (
            "sliver_area_threshold",
            "sliver_compactness_threshold",
            "tiny_island_area_threshold",
            "isolation_distance",
            "noise_area_threshold",
            "merge_tolerance",
            "max_target_area_change",
        ):
            _non_negative(name, getattr(self, name))


@dataclass(frozen=True, slots=True)
class SmallPolygonFinding:
    feature_index: int
    issue_type: SmallPolygonIssueType
    recommendation: Recommendation
    area: float
    compactness: float
    source_wkt: str
    target_index: int | None = None
    target_before_wkt: str | None = None
    preview_wkt: str | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class SmallPolygonReport:
    feature_count: int
    findings: tuple[SmallPolygonFinding, ...]

    @property
    def recommendation_counts(self) -> dict[str, int]:
        return {
            item.value: sum(f.recommendation == item for f in self.findings)
            for item in Recommendation
        }
