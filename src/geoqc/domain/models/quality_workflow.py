"""Compatibility imports for the split quality-workflow domain modules."""

from geoqc.domain.models.audit_result import (
    AuditResultExporter,
    DatasetAuditResult,
    WorkflowArtifacts,
)
from geoqc.domain.models.quality_profile import (
    QualityGatePolicy,
    QualityPreset,
    QualityProfile,
)
from geoqc.domain.models.scoring import (
    CategoryScore,
    CrsGuardResult,
    CrsUnitStatus,
    ScoreDeduction,
    ScoringPolicy,
)
from geoqc.domain.models.topology import (
    AttributeOverlapPolicy,
    AttributeRule,
    AttributeRuleType,
    DatasetIssue,
    DatasetLayer,
    IssueGeometryKind,
    RepairPlan,
    RepairPlanAction,
    RepairPlanConflict,
    RepairRisk,
    TopologyRule,
    TopologyRuleType,
)

__all__ = [
    "AttributeOverlapPolicy",
    "AttributeRule",
    "AttributeRuleType",
    "AuditResultExporter",
    "CategoryScore",
    "CrsGuardResult",
    "CrsUnitStatus",
    "DatasetAuditResult",
    "DatasetIssue",
    "DatasetLayer",
    "IssueGeometryKind",
    "QualityGatePolicy",
    "QualityPreset",
    "QualityProfile",
    "RepairPlan",
    "RepairPlanAction",
    "RepairPlanConflict",
    "RepairRisk",
    "ScoreDeduction",
    "ScoringPolicy",
    "TopologyRule",
    "TopologyRuleType",
    "WorkflowArtifacts",
]
