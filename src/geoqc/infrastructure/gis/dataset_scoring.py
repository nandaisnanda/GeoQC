"""Dataset scoring for the canonical dataset workflow."""

from collections.abc import Sequence

from geoqc.domain.models import (
    DatasetAuditResult,
    DatasetIssue,
    ScoringPolicy,
)
from geoqc.infrastructure.gis.quality_workflow import (
    score_issues,
)


def _rebuild_result(
    base: DatasetAuditResult, issues: Sequence[DatasetIssue], scoring: ScoringPolicy | None
) -> DatasetAuditResult:
    unique = {
        (
            item.fingerprint,
            item.code,
            item.feature_index,
            item.related_feature_index,
            item.geometry_wkt,
        ): item
        for item in issues
    }
    ordered = tuple(sorted(unique.values(), key=lambda item: (item.category, item.fingerprint)))
    scores, deductions, overall = score_issues(ordered, base.feature_count, scoring)
    return DatasetAuditResult(
        dataset_name=base.dataset_name,
        preset=base.preset,
        feature_count=base.feature_count,
        issues=ordered,
        crs_guard=base.crs_guard,
        category_scores=scores,
        quality_score=overall,
        score_deductions=deductions,
        profile_name=base.profile_name,
        schema_version=base.schema_version,
    )
