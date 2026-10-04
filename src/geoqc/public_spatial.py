"""Public spatial-intelligence convenience functions."""

from collections.abc import Sequence

from shapely.geometry.base import BaseGeometry

from geoqc.application.services.repair_recommendation import RepairRecommendationEngine
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
    RoadNetworkRepairConfig,
    RoadNetworkRepairResult,
    RoadNetworkReport,
    SmallPolygonConfig,
    SmallPolygonReport,
)
from geoqc.infrastructure.gis.shapely_enterprise_spatial import (
    ShapelyDatasetComparator,
    ShapelySpatialConflictAnalyzer,
    ShapelySpatialDuplicateDetector,
)
from geoqc.infrastructure.gis.shapely_spatial_intelligence import (
    ShapelyBoundarySnapper,
    ShapelyRoadNetworkAnalyzer,
    ShapelyRoadNetworkRepairer,
    ShapelySmallPolygonAnalyzer,
)
from geoqc.public_helpers import require_geometry, to_wkt

_boundary_snapper = ShapelyBoundarySnapper()
_road_analyzer = ShapelyRoadNetworkAnalyzer()
_road_repairer = ShapelyRoadNetworkRepairer()
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
        [to_wkt(require_geometry(item)) for item in geometries],
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
        [to_wkt(require_geometry(item)) for item in geometries],
        config or BoundarySnapConfig(),
    )


def analyze_road_network(
    geometries: Sequence[BaseGeometry], config: RoadNetworkConfig | None = None
) -> RoadNetworkReport:
    """Detect connectivity and duplicate issues in a road network."""
    return _road_analyzer.analyze(
        [to_wkt(require_geometry(item)) for item in geometries],
        config or RoadNetworkConfig(),
    )


def repair_road_network(
    geometries: Sequence[BaseGeometry], config: RoadNetworkRepairConfig | None = None
) -> RoadNetworkRepairResult:
    """Snap small endpoint gaps and return fully noded road segments.

    The source geometries are not mutated. Every output segment contains input
    feature indices so dataset attributes can be restored by callers.
    """
    return _road_repairer.repair(
        [to_wkt(require_geometry(item)) for item in geometries],
        config or RoadNetworkRepairConfig(),
    )


def analyze_small_polygons(
    geometries: Sequence[BaseGeometry], config: SmallPolygonConfig | None = None
) -> SmallPolygonReport:
    """Classify suspicious small polygons and return repair previews."""
    return _small_polygon_analyzer.analyze(
        [to_wkt(require_geometry(item)) for item in geometries],
        config or SmallPolygonConfig(),
    )
