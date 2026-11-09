"""Snapshot of the names exported by ``import geoqc``.

Removing or renaming an internal module must never change this list. If a name is
added or removed on purpose, update the snapshot in the same commit and record the
change in CHANGELOG.md.
"""

import importlib

import pytest

import geoqc

PUBLIC_NAMES = (
    "AttributeColumnSchema",
    "AttributeDataType",
    "AttributeOverlapPolicy",
    "AttributeRule",
    "AttributeRuleType",
    "AttributeSchema",
    "AuditCheckResult",
    "AuditDatasetMetadata",
    "AuditIssue",
    "BoundarySnapConfig",
    "BoundarySnapResult",
    "CategoryScore",
    "CheckStatus",
    "ConflictPolicy",
    "CoverageRepairResult",
    "CrsGuardResult",
    "CrsUnitStatus",
    "DatasetAuditReport",
    "DatasetAuditResult",
    "DatasetDifferenceReport",
    "DatasetIssue",
    "DatasetLayer",
    "DatasetSnapshot",
    "GeometryIssueType",
    "GeometryRepairResult",
    "GeometryValidationIssue",
    "GeometryValidationResult",
    "IssueGeometryKind",
    "PriorityWeights",
    "QualityGatePolicy",
    "QualityPreset",
    "QualityProfile",
    "RepairCandidate",
    "RepairConfig",
    "RepairIssueType",
    "RepairPlan",
    "RepairPlanAction",
    "RepairPlanConflict",
    "RepairRecommendation",
    "RepairRisk",
    "RepairSession",
    "RoadComponentConnectionConfig",
    "RoadComponentConnectionResult",
    "RoadComponentConnector",
    "RoadNetworkConfig",
    "RoadNetworkRepairConfig",
    "RoadNetworkRepairResult",
    "RoadNetworkReport",
    "RoadRepairSegment",
    "ScoreDeduction",
    "ScoringPolicy",
    "SmallPolygonConfig",
    "SmallPolygonReport",
    "SpatialConflictReport",
    "SpatialDuplicateConfig",
    "SpatialDuplicateReport",
    "SpatialLayer",
    "TopologyRule",
    "TopologyRuleType",
    "WorkflowArtifacts",
    "__version__",
    "analyze_road_network",
    "analyze_small_polygons",
    "analyze_spatial_conflicts",
    "assess_crs",
    "audit_dataset",
    "audit_file",
    "audit_geodataframe",
    "audit_geometries",
    "audit_layers",
    "build_quality_report",
    "build_repair_plan",
    "compare_datasets",
    "connect_road_components",
    "detect_spatial_duplicates",
    "dump_quality_profile",
    "evaluate_topology_rules",
    "issues_to_geodataframe",
    "load_quality_profile",
    "open_repair_session",
    "prioritize_repairs",
    "quality_profile_from_dict",
    "repair_geometries",
    "repair_geometries_safely",
    "repair_geometry",
    "repair_road_network",
    "run_quality_workflow",
    "snap_boundaries",
    "validate_geometry",
    "write_audit_report",
    "write_issue_layers",
)

CANONICAL_IMPORTS = (
    "audit_dataset",
    "audit_geodataframe",
    "evaluate_topology_rules",
    "assess_crs",
    "issues_to_geodataframe",
    "audit_geometries",
)


def test_all_matches_the_recorded_snapshot() -> None:
    assert sorted(geoqc.__all__) == sorted(PUBLIC_NAMES)
    assert len(geoqc.__all__) == len(set(geoqc.__all__)) == 91


@pytest.mark.parametrize("name", PUBLIC_NAMES)
def test_every_public_name_resolves_on_the_package(name: str) -> None:
    assert hasattr(geoqc, name)


@pytest.mark.parametrize("name", CANONICAL_IMPORTS)
def test_canonical_entry_points_are_callable(name: str) -> None:
    assert callable(getattr(geoqc, name))


def test_star_import_exposes_exactly_the_public_names() -> None:
    namespace: dict[str, object] = {}
    exec("from geoqc import *", namespace)  # noqa: S102
    exported = {key for key in namespace if not key.startswith("__")}
    assert exported == {name for name in PUBLIC_NAMES if not name.startswith("__")}


def test_removed_facade_modules_are_gone() -> None:
    for module in (
        "geoqc.infrastructure.gis.quality_workflow",
        "geoqc.domain.models.quality_workflow",
        "geoqc.infrastructure.gis.dataset_scoring",
        "geoqc.infrastructure.gis.legacy",
        "geoqc.application.services.spatial_intelligence",
        "geoqc.application.ports.spatial_intelligence",
        "geoqc.application.streaming.processor",
    ):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module)
