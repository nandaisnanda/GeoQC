"""Deterministic repair recommendation and prioritization service."""

from collections.abc import Sequence

from geoqc.domain.models.enterprise_spatial import (
    PriorityWeights,
    RepairCandidate,
    RepairRecommendation,
)


class RepairRecommendationEngine:
    """Rank repairs with auditable arithmetic and issue-type rules; no AI is used."""

    _ACTIONS = {
        "building_in_river": "Relocate or clip the building after authoritative review.",
        "road_river_crossing": "Validate the crossing and add a bridge/culvert relation.",
        "inter_agency_overlap": "Reconcile ownership against the authoritative boundary.",
        "boundary_conflict": "Snap or adjudicate the disputed boundary.",
        "duplicate": "Keep the authoritative feature and remove the duplicate.",
    }

    def prioritize(
        self, candidates: Sequence[RepairCandidate], weights: PriorityWeights | None = None
    ) -> tuple[RepairRecommendation, ...]:
        weights = weights or PriorityWeights()
        maximum_area = max((item.area for item in candidates), default=0.0)
        maximum_count = max((item.feature_count for item in candidates), default=0)
        scored: list[tuple[float, RepairCandidate, str]] = []
        for item in candidates:
            area_score = 100 * item.area / maximum_area if maximum_area else 0.0
            count_score = 100 * item.feature_count / maximum_count if maximum_count else 0.0
            score = (
                weights.severity * item.severity
                + weights.impact * item.impact
                + weights.area * area_score
                + weights.feature_count * count_score
            )
            rationale = (
                f"severity={item.severity:.1f}, impact={item.impact:.1f}, "
                f"area={area_score:.1f}, features={count_score:.1f}; deterministic weighted rule"
            )
            scored.append((round(score, 2), item, rationale))
        scored.sort(key=lambda value: (-value[0], value[1].issue_id))
        return tuple(
            RepairRecommendation(
                rank=index,
                issue_id=item.issue_id,
                priority_score=score,
                action=self._ACTIONS.get(
                    item.issue_type, "Review and repair using the least destructive operation."
                ),
                rationale=rationale,
            )
            for index, (score, item, rationale) in enumerate(scored, start=1)
        )
