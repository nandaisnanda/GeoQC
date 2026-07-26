"""Public API for GeoQC geometry quality checks and topology repair."""

from collections.abc import Sequence

import shapely
from shapely.geometry.base import BaseGeometry

from geoqc.application.services.repair_recommendation import RepairRecommendationEngine
from geoqc.application.services.topology_repair import RepairSession
from geoqc.domain.models import (
    CoverageRepairResult,
    GeometryIssueType,
    GeometryRepairResult,
    GeometryValidationIssue,
    GeometryValidationResult,
    RepairConfig,
)
from geoqc.domain.models.enterprise_spatial import (
    ConflictPolicy,
    DatasetDifferenceReport,
    DatasetSnapshot,
    PriorityWeights,
    RepairCandidate,
    RepairRecommendation,
    SpatialConflictReport,
    SpatialDuplicateConfig,
    SpatialDuplicateReport,
    SpatialLayer,
)
from geoqc.domain.models.spatial_intelligence import (
    BoundarySnapConfig,
    BoundarySnapResult,
    RoadNetworkConfig,
    RoadNetworkReport,
    SmallPolygonConfig,
    SmallPolygonReport,
)
from geoqc.infrastructure.gis.shapely_enterprise_spatial import (
    ShapelyDatasetComparator,
    ShapelySpatialConflictAnalyzer,
    ShapelySpatialDuplicateDetector,
)
from geoqc.infrastructure.gis.shapely_geometry_validator import ShapelyGeometryValidator
from geoqc.infrastructure.gis.shapely_spatial_intelligence import (
    ShapelyBoundarySnapper,
    ShapelyRoadNetworkAnalyzer,
    ShapelySmallPolygonAnalyzer,
)
from geoqc.infrastructure.gis.shapely_topology_repairer import ShapelyTopologyRepairer

__all__ = [
    "CoverageRepairResult",
    "BoundarySnapConfig",
    "BoundarySnapResult",
    "GeometryIssueType",
    "GeometryRepairResult",
    "GeometryValidationIssue",
    "GeometryValidationResult",
    "RepairConfig",
    "RepairSession",
    "RoadNetworkConfig",
    "RoadNetworkReport",
    "SmallPolygonConfig",
    "SmallPolygonReport",
    "ConflictPolicy",
    "DatasetDifferenceReport",
    "DatasetSnapshot",
    "PriorityWeights",
    "RepairCandidate",
    "RepairRecommendation",
    "SpatialConflictReport",
    "SpatialDuplicateConfig",
    "SpatialDuplicateReport",
    "SpatialLayer",
    "analyze_road_network",
    "analyze_small_polygons",
    "analyze_spatial_conflicts",
    "compare_datasets",
    "detect_spatial_duplicates",
    "prioritize_repairs",
    "__version__",
    "open_repair_session",
    "repair_geometries",
    "repair_geometry",
    "snap_boundaries",
    "validate_geometry",
]

__version__: str = "0.1.0"

_geometry_validator = ShapelyGeometryValidator()
_topology_repairer = ShapelyTopologyRepairer(_geometry_validator)
_boundary_snapper = ShapelyBoundarySnapper()
_road_analyzer = ShapelyRoadNetworkAnalyzer()
_small_polygon_analyzer = ShapelySmallPolygonAnalyzer()
_duplicate_detector = ShapelySpatialDuplicateDetector()
_dataset_comparator = ShapelyDatasetComparator()
_conflict_analyzer = ShapelySpatialConflictAnalyzer()
_recommendation_engine = RepairRecommendationEngine()


def detect_spatial_duplicates(
    geometries: Sequence[BaseGeometry], config: SpatialDuplicateConfig | None = None
) -> SpatialDuplicateReport:
    """Detect exact and near spatial duplicates with indexed candidate search."""
    return _duplicate_detector.detect(
        [_to_wkt(_require_geometry(item)) for item in geometries],
        config or SpatialDuplicateConfig(),
    )


def compare_datasets(
    left: DatasetSnapshot, right: DatasetSnapshot, *, match_threshold: float = 0.5
) -> DatasetDifferenceReport:
    """Compare geometry, attributes, CRS, schema, and aggregate boundaries."""
    return _dataset_comparator.compare(left, right, match_threshold=match_threshold)


def analyze_spatial_conflicts(
    layers: Sequence[SpatialLayer], policy: ConflictPolicy | None = None
) -> SpatialConflictReport:
    """Detect configured semantic conflicts between spatial layers."""
    return _conflict_analyzer.analyze(layers, policy)


def prioritize_repairs(
    candidates: Sequence[RepairCandidate], weights: PriorityWeights | None = None
) -> tuple[RepairRecommendation, ...]:
    """Rank repair candidates using a deterministic, explainable rule engine."""
    return _recommendation_engine.prioritize(candidates, weights)


def snap_boundaries(
    geometries: Sequence[BaseGeometry], config: BoundarySnapConfig | None = None
) -> BoundarySnapResult:
    """Preview conservative snapping between nearby polygon boundaries."""
    return _boundary_snapper.snap(
        [_to_wkt(_require_geometry(item)) for item in geometries],
        config or BoundarySnapConfig(),
    )


def analyze_road_network(
    geometries: Sequence[BaseGeometry], config: RoadNetworkConfig | None = None
) -> RoadNetworkReport:
    """Detect connectivity and duplicate issues in a road network."""
    return _road_analyzer.analyze(
        [_to_wkt(_require_geometry(item)) for item in geometries],
        config or RoadNetworkConfig(),
    )


def analyze_small_polygons(
    geometries: Sequence[BaseGeometry], config: SmallPolygonConfig | None = None
) -> SmallPolygonReport:
    """Classify suspicious small polygons and return repair previews."""
    return _small_polygon_analyzer.analyze(
        [_to_wkt(_require_geometry(item)) for item in geometries],
        config or SmallPolygonConfig(),
    )


def validate_geometry(geometry: BaseGeometry) -> GeometryValidationResult:
    """Validate one Shapely geometry for topology and duplicate-vertex issues.

    Args:
        geometry: Any Shapely geometry instance.

    Returns:
        An immutable result containing the geometry type and detected issues.

    Raises:
        TypeError: If ``geometry`` is not a Shapely geometry.
    """
    return _geometry_validator.validate(geometry)


def repair_geometry(
    geometry: BaseGeometry, config: RepairConfig | None = None
) -> GeometryRepairResult:
    """Repair the intrinsic topology of one Shapely geometry, minimally.

    Fixes self-intersections, invalid rings, duplicate vertices, and degenerate
    slivers while changing the original shape as little as possible. The result
    stores both the original and repaired geometry as WKT.

    Args:
        geometry: Any Shapely geometry instance.
        config: Optional thresholds; sensible conservative defaults are used.

    Returns:
        A reversible, reportable repair result.

    Raises:
        TypeError: If ``geometry`` is not a Shapely geometry.
    """
    if not isinstance(geometry, BaseGeometry):
        raise TypeError("geometry must be a Shapely BaseGeometry")
    return _topology_repairer.repair(_to_wkt(geometry), config or RepairConfig())


def repair_geometries(
    geometries: Sequence[BaseGeometry], config: RepairConfig | None = None
) -> CoverageRepairResult:
    """Repair a set of geometries as one coverage in a single pass.

    Each geometry's intrinsic defects are fixed first, then cross-feature
    overlaps are erased (earlier features keep disputed area) and enclosed gaps
    below the configured area are filled into the neighbour with the longest
    shared boundary.

    Args:
        geometries: Shapely geometries forming one topological coverage.
        config: Optional thresholds; sensible conservative defaults are used.

    Returns:
        Before/after WKT for every feature and an aggregate repair report.

    Raises:
        TypeError: If any element is not a Shapely geometry.
    """
    wkts = [_to_wkt(_require_geometry(geometry)) for geometry in geometries]
    return _topology_repairer.repair_coverage(wkts, config or RepairConfig())


def open_repair_session(
    geometries: Sequence[BaseGeometry], config: RepairConfig | None = None
) -> RepairSession:
    """Create a stateful repair session supporting preview, apply, and undo.

    Args:
        geometries: Shapely geometries forming one topological coverage.
        config: Optional thresholds; sensible conservative defaults are used.

    Returns:
        A session whose ``preview``/``apply``/``undo`` operate on WKT snapshots.

    Raises:
        TypeError: If any element is not a Shapely geometry.
    """
    wkts = [_to_wkt(_require_geometry(geometry)) for geometry in geometries]
    return RepairSession(wkts, _topology_repairer, config)


def _require_geometry(geometry: BaseGeometry) -> BaseGeometry:
    if not isinstance(geometry, BaseGeometry):
        raise TypeError("geometry must be a Shapely BaseGeometry")
    return geometry


def _to_wkt(geometry: BaseGeometry) -> str:
    return str(shapely.to_wkt(geometry, rounding_precision=-1))
