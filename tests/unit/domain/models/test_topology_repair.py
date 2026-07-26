"""Tests for the topology-repair domain value objects."""

import pytest

from geoqc.domain.models.topology_repair import (
    CoverageRepairResult,
    FeatureRepairResult,
    GeometryRepairResult,
    RepairAction,
    RepairConfig,
    RepairIssueType,
    RepairMetrics,
    RepairReport,
    RepairStatus,
)


def _result(
    *,
    status: RepairStatus = RepairStatus.REPAIRED,
    actions: tuple[RepairAction, ...] = (),
    before: str = "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
    after: str = "POLYGON ((0 0, 1 0, 1 1, 0 0))",
    metrics: RepairMetrics | None = None,
) -> GeometryRepairResult:
    return GeometryRepairResult(
        geometry_type="Polygon",
        status=status,
        before_wkt=before,
        after_wkt=after,
        actions=actions,
        metrics=metrics or RepairMetrics(1.0, 0.5, 5, 4, 0.25),
    )


def test_repair_config_rejects_negative_thresholds() -> None:
    """Negative thresholds are a programming error and must be rejected."""
    with pytest.raises(ValueError, match="must be non-negative"):
        RepairConfig(gap_area_threshold=-1.0)


def test_repair_metrics_report_signed_deltas() -> None:
    """Area and vertex deltas expose the direction of change."""
    metrics = RepairMetrics(
        area_before=2.0,
        area_after=1.5,
        vertex_count_before=6,
        vertex_count_after=4,
        shape_shift=0.1,
    )

    assert metrics.area_delta == pytest.approx(-0.5)
    assert metrics.vertex_delta == -2


def test_geometry_repair_result_is_changed_and_has_action() -> None:
    """A repaired result with different WKT reports change and its actions."""
    action = RepairAction(RepairIssueType.SELF_INTERSECTION, "make_valid", "reason")
    result = _result(actions=(action,))

    assert result.is_changed
    assert result.has_action(RepairIssueType.SELF_INTERSECTION)
    assert not result.has_action(RepairIssueType.GAP)


def test_unchanged_result_is_not_changed() -> None:
    """An unchanged result never reports change even with equal WKT."""
    result = _result(status=RepairStatus.UNCHANGED, before="X", after="X")

    assert not result.is_changed


def test_repair_report_aggregates_counts_and_actions() -> None:
    """The report summarizes statuses, action counts, and shape metrics."""
    repaired = FeatureRepairResult(
        0,
        _result(
            actions=(RepairAction(RepairIssueType.OVERLAP, "erase_overlap", "d"),),
            metrics=RepairMetrics(4.0, 3.0, 4, 4, 0.5),
        ),
    )
    unchanged = FeatureRepairResult(
        1, _result(status=RepairStatus.UNCHANGED, before="Y", after="Y")
    )
    failed = FeatureRepairResult(2, _result(status=RepairStatus.FAILED))
    report = RepairReport((repaired, unchanged, failed))

    assert report.total == 3
    assert report.repaired_count == 1
    assert report.unchanged_count == 1
    assert report.failed_count == 1
    assert report.action_counts == {"overlap": 1}
    assert report.total_area_delta == pytest.approx(-1.0 + -0.5 + -0.5)
    assert report.max_shape_shift == pytest.approx(0.5)


def test_repair_report_to_dict_is_serializable() -> None:
    """to_dict emits a JSON-friendly structure with per-feature detail."""
    action = RepairAction(RepairIssueType.GAP, "fill_gap", "filled 0.1")
    report = RepairReport((FeatureRepairResult(3, _result(actions=(action,))),))

    payload = report.to_dict()

    assert payload["total"] == 1
    assert payload["action_counts"] == {"gap": 1}
    features = payload["features"]
    assert isinstance(features, list)
    assert features[0]["feature_index"] == 3
    assert features[0]["actions"][0]["strategy"] == "fill_gap"


def test_empty_report_has_zero_shape_shift() -> None:
    """An empty report degrades gracefully to zero maxima."""
    report = RepairReport(())

    assert report.total == 0
    assert report.max_shape_shift == 0.0
    assert report.action_counts == {}


def test_coverage_result_pairs_before_and_after() -> None:
    """Coverage results carry aligned before/after WKT and a report."""
    result = CoverageRepairResult(
        before_wkt=("A", "B"), after_wkt=("A2", "B2"), report=RepairReport(())
    )

    assert result.before_wkt == ("A", "B")
    assert result.after_wkt == ("A2", "B2")
    assert result.report.total == 0
