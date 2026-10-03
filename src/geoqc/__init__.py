"""Public API for GeoQC geometry quality checks and topology repair."""

from collections.abc import Sequence

import shapely
from shapely.geometry.base import BaseGeometry

from geoqc.application.services.repair_recommendation import RepairRecommendationEngine
from geoqc.application.services.topology_repair import RepairSession
from geoqc.domain.models import (
    AttributeColumnSchema,
    AttributeDataType,
    AttributeOverlapPolicy,
    AttributeRule,
    AttributeRuleType,
    AttributeSchema,
    AuditCheckResult,
    AuditDatasetMetadata,
    AuditIssue,
    CategoryScore,
    CheckStatus,
    CoverageRepairResult,
    CrsGuardResult,
    CrsUnitStatus,
    DatasetAuditReport,
    DatasetAuditResult,
    DatasetIssue,
    DatasetLayer,
    GeometryIssueType,
    GeometryRepairResult,
    GeometryValidationIssue,
    GeometryValidationResult,
    IssueGeometryKind,
    QualityGatePolicy,
    QualityPreset,
    QualityProfile,
    RepairConfig,
    RepairIssueType,
    RepairPlan,
    RepairPlanAction,
    RepairPlanConflict,
    RepairRisk,
    ScoreDeduction,
    ScoringPolicy,
    TopologyRule,
    TopologyRuleType,
    WorkflowArtifacts,
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
from geoqc.domain.models.quality_report import QualityReport, QualityReportIssue
from geoqc.domain.models.spatial_intelligence import (
    BoundarySnapConfig,
    BoundarySnapResult,
    RoadNetworkConfig,
    RoadNetworkRepairConfig,
    RoadNetworkRepairResult,
    RoadNetworkReport,
    RoadRepairSegment,
    SmallPolygonConfig,
    SmallPolygonReport,
)
from geoqc.infrastructure.gis.dataset_audit import audit_dataset
from geoqc.infrastructure.gis.dataset_workflow import (
    audit_file,
    audit_geodataframe,
    audit_layers,
    build_repair_plan,
    dump_quality_profile,
    load_quality_profile,
    quality_profile_from_dict,
    run_quality_workflow,
    write_audit_report,
    write_issue_layers,
)
from geoqc.infrastructure.gis.quality_workflow import (
    assess_crs,
    evaluate_topology_rules,
    issues_to_geodataframe,
)
from geoqc.infrastructure.gis.quality_workflow import (
    audit_dataset as audit_geometries,
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
    ShapelyRoadNetworkRepairer,
    ShapelySmallPolygonAnalyzer,
)
from geoqc.infrastructure.gis.shapely_topology_repairer import ShapelyTopologyRepairer

__all__ = [
    "AttributeOverlapPolicy",
    "AttributeColumnSchema",
    "AttributeDataType",
    "AttributeRule",
    "AttributeRuleType",
    "AttributeSchema",
    "AuditCheckResult",
    "AuditDatasetMetadata",
    "AuditIssue",
    "CategoryScore",
    "CoverageRepairResult",
    "CrsGuardResult",
    "CrsUnitStatus",
    "CheckStatus",
    "DatasetAuditResult",
    "DatasetAuditReport",
    "DatasetIssue",
    "DatasetLayer",
    "BoundarySnapConfig",
    "BoundarySnapResult",
    "GeometryIssueType",
    "GeometryRepairResult",
    "GeometryValidationIssue",
    "GeometryValidationResult",
    "IssueGeometryKind",
    "QualityGatePolicy",
    "QualityPreset",
    "QualityProfile",
    "RepairConfig",
    "RepairIssueType",
    "RepairPlan",
    "RepairPlanAction",
    "RepairPlanConflict",
    "RepairRisk",
    "RepairSession",
    "RoadNetworkConfig",
    "RoadNetworkReport",
    "RoadNetworkRepairConfig",
    "RoadNetworkRepairResult",
    "RoadRepairSegment",
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
    "ScoreDeduction",
    "ScoringPolicy",
    "TopologyRule",
    "TopologyRuleType",
    "WorkflowArtifacts",
    "analyze_road_network",
    "assess_crs",
    "audit_geometries",
    "audit_dataset",
    "audit_file",
    "audit_geodataframe",
    "audit_layers",
    "build_quality_report",
    "build_repair_plan",
    "repair_road_network",
    "analyze_small_polygons",
    "analyze_spatial_conflicts",
    "compare_datasets",
    "detect_spatial_duplicates",
    "evaluate_topology_rules",
    "dump_quality_profile",
    "issues_to_geodataframe",
    "load_quality_profile",
    "prioritize_repairs",
    "quality_profile_from_dict",
    "__version__",
    "open_repair_session",
    "repair_geometries",
    "repair_geometries_safely",
    "repair_geometry",
    "run_quality_workflow",
    "snap_boundaries",
    "validate_geometry",
    "write_audit_report",
    "write_issue_layers",
]

__version__: str = "0.1.0"

_geometry_validator = ShapelyGeometryValidator()
_topology_repairer = ShapelyTopologyRepairer(_geometry_validator)
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


def repair_road_network(
    geometries: Sequence[BaseGeometry], config: RoadNetworkRepairConfig | None = None
) -> RoadNetworkRepairResult:
    """Snap small endpoint gaps and return fully noded road segments.

    The source geometries are not mutated. Every output segment contains input
    feature indices so dataset attributes can be restored by callers.
    """
    return _road_repairer.repair(
        [_to_wkt(_require_geometry(item)) for item in geometries],
        config or RoadNetworkRepairConfig(),
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


def repair_geometries_safely(geometries: Sequence[BaseGeometry]) -> CoverageRepairResult:
    """Apply only shape-preserving duplicate-vertex cleanup.

    Ambiguous operations such as invalid-geometry reconstruction, sliver
    removal, overlap resolution, and gap filling remain disabled. This is the
    appropriate default for unattended jobs and future QGIS "fix safe" UI.
    """
    return repair_geometries(
        geometries,
        RepairConfig(
            fix_invalid=False,
            remove_slivers=False,
            resolve_overlaps=False,
            fill_gaps=False,
            max_shape_shift=0.0,
            max_relative_area_change=0.0,
        ),
    )


def build_quality_report(result: DatasetAuditResult) -> QualityReport:
    """Convert a dataset audit into the existing renderer-ready report model."""
    issues = tuple(
        QualityReportIssue(
            code=item.code,
            title=item.title,
            description=item.message,
            severity=item.severity,
            category=item.category.title(),
            recommendation=item.recommendation,
            location=(
                f"{item.layer or result.dataset_name}, feature {item.feature_index}"
                if item.feature_index is not None
                else item.layer or result.dataset_name
            ),
        )
        for item in result.issues
    )
    return QualityReport(
        title="GeoQC dataset quality report",
        dataset_name=result.dataset_name,
        total_checks=max(1, result.feature_count),
        passed_checks=max(
            0,
            result.feature_count
            - len({item.feature_index for item in result.issues if item.feature_index is not None}),
        ),
        issues=issues,
        summary=(
            f"Quality score {result.quality_score:.2f}/100; "
            f"{len(result.issues)} issue(s) found across {result.feature_count} feature(s)."
        ),
    )


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
