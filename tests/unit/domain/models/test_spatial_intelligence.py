from collections.abc import Callable

import pytest

from geoqc.domain.models.spatial_intelligence import (
    BoundarySnapConfig,
    Recommendation,
    RoadFinding,
    RoadIssueType,
    RoadNetworkConfig,
    RoadNetworkReport,
    SmallPolygonConfig,
)


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: BoundarySnapConfig(tolerance=0), "tolerance must be positive"),
        (
            lambda: BoundarySnapConfig(max_relative_area_change=-1),
            "max_relative_area_change must be non-negative",
        ),
        (
            lambda: RoadNetworkConfig(duplicate_overlap_ratio=1.1),
            "duplicate_overlap_ratio must be between zero and one",
        ),
        (
            lambda: SmallPolygonConfig(noise_area_threshold=-1),
            "noise_area_threshold must be non-negative",
        ),
    ],
)
def test_configs_reject_unsafe_thresholds(factory: Callable[[], object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_road_report_serializes_all_issue_categories() -> None:
    report = RoadNetworkReport(
        1,
        (
            RoadFinding(
                RoadIssueType.DEAD_END,
                (0,),
                "POINT (0 0)",
                "Endpoint has degree one",
            ),
        ),
    )

    payload = report.to_dict()

    assert payload["feature_count"] == 1
    assert report.issue_counts[RoadIssueType.DEAD_END.value] == 1
    assert set(report.issue_counts) == {item.value for item in RoadIssueType}
    assert payload["findings"][0]["issue_type"] == "dead_end"  # type: ignore[index]


def test_recommendations_are_stable_machine_readable_values() -> None:
    assert {item.value for item in Recommendation} == {"delete", "merge", "ignore"}
