"""Repair plan for the canonical dataset workflow."""

from geoqc.domain.models import (
    DatasetAuditResult,
    RepairPlan,
    RepairPlanAction,
    RepairPlanConflict,
    RepairRisk,
)

_STRATEGIES = {
    "duplicate_vertex": "remove_duplicate_vertices",
    "invalid_geometry": "make_valid",
    "self_intersection": "make_valid",
    "ring_error": "repair_ring",
    "overlap": "resolve_overlap_by_policy",
    "gap": "assign_gap_by_policy",
    "broken_connection": "snap_endpoint",
    "unnoded_intersection": "node_intersection",
    "duplicate_segment": "remove_duplicate_segment",
}


def build_repair_plan(result: DatasetAuditResult) -> RepairPlan:
    """Build an explainable plan and flag competing non-safe actions per feature."""
    actions = tuple(
        RepairPlanAction(
            issue_fingerprint=issue.fingerprint,
            feature_index=issue.feature_index,
            issue_type=issue.issue_type,
            strategy=_STRATEGIES.get(issue.issue_type, "manual_review"),
            risk=issue.repair_risk,
            automatic=issue.repair_risk is RepairRisk.SAFE,
        )
        for issue in result.issues
        if issue.issue_type in _STRATEGIES
    )
    by_feature: dict[int | None, list[RepairPlanAction]] = {}
    for action in actions:
        by_feature.setdefault(action.feature_index, []).append(action)
    conflicts = tuple(
        RepairPlanConflict(
            feature_index=feature_index,
            issue_fingerprints=tuple(item.issue_fingerprint for item in selected),
            reason="Multiple reviewed repair strategies target the same feature.",
        )
        for feature_index, selected in by_feature.items()
        if feature_index is not None
        and len([item for item in selected if item.risk is not RepairRisk.SAFE]) > 1
    )
    return RepairPlan(actions, conflicts)
