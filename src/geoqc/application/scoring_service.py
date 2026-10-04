"""Deterministic scoring for canonical dataset findings."""

from collections.abc import Sequence

from geoqc.domain.models import CategoryScore, DatasetIssue, ScoreDeduction, ScoringPolicy


def score_issues(
    issues: Sequence[DatasetIssue],
    feature_count: int,
    policy: ScoringPolicy | None = None,
) -> tuple[tuple[CategoryScore, ...], tuple[ScoreDeduction, ...], float]:
    """Score findings with size-normalized penalties and explain every deduction."""
    selected_policy = policy or ScoringPolicy()
    if feature_count < 0:
        raise ValueError("feature_count must be non-negative")
    denominator = max(1, feature_count)
    scores: list[CategoryScore] = []
    deductions: list[ScoreDeduction] = []
    for category in selected_policy.category_weights:
        category_issues = [item for item in issues if item.category == category]
        points = 0.0
        entity_points: dict[tuple[int | None, int | None], float] = {}
        for issue in category_issues:
            affected = (
                len(set(issue.feature_indices)) / denominator if issue.feature_indices else 1.0
            )
            raw = selected_policy.severity_penalties[issue.severity] * min(1.0, affected)
            entity = (issue.feature_index, issue.related_feature_index)
            entity_remaining = max(
                0.0,
                selected_policy.repeated_feature_cap - entity_points.get(entity, 0.0),
            )
            category_remaining = max(0.0, selected_policy.category_caps[category] - points)
            deduction = min(raw, entity_remaining, category_remaining)
            entity_points[entity] = entity_points.get(entity, 0.0) + deduction
            points += deduction
            deductions.append(
                ScoreDeduction(
                    category=category,
                    issue_fingerprint=issue.fingerprint,
                    severity=issue.severity,
                    points=round(deduction, 4),
                    explanation=(
                        f"{issue.title}: {issue.severity.value} base penalty "
                        f"{selected_policy.severity_penalties[issue.severity]:g} Ã— "
                        f"affected proportion {affected:.6f}; bounded by the "
                        f"{selected_policy.repeated_feature_cap:g}-point repeated-feature "
                        f"cap and {selected_policy.category_caps[category]:g}-point category cap."
                    ),
                )
            )
        scores.append(
            CategoryScore(category, round(max(0.0, 100.0 - points), 2), len(category_issues))
        )
    weight_total = sum(selected_policy.category_weights.values())
    score_by_category = {item.category: item.score for item in scores}
    overall = (
        sum(
            score_by_category[category] * weight
            for category, weight in selected_policy.category_weights.items()
        )
        / weight_total
    )
    return tuple(scores), tuple(deductions), round(overall, 2)
