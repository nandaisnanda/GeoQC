from collections import Counter

import pytest

from geoqc.application.streaming.collector import RuleResultCollector
from geoqc.application.streaming.geometry import (
    GeometryChunkResult,
    GeometryFinding,
    GeometryResultCollector,
)
from geoqc.domain.rules.models import EngineResult, ResultStatus, RuleFinding, RuleResult


def test_rule_collector_preserves_order_and_merges_findings() -> None:
    collector = RuleResultCollector()
    collector.add(
        EngineResult(
            (
                RuleResult.passed("valid-geometry"),
                RuleResult.failed("required", RuleFinding("missing", feature_id=1)),
            )
        )
    )
    collector.add(
        EngineResult(
            (
                RuleResult.failed("valid-geometry", RuleFinding("invalid", feature_id=2)),
                RuleResult.passed("required"),
            )
        )
    )

    result = collector.finish()

    assert [item.rule_id for item in result.results] == ["valid-geometry", "required"]
    assert [item.status for item in result.results] == [ResultStatus.FAILED, ResultStatus.FAILED]
    assert result.results[0].findings[0].feature_id == 2


def test_rule_collector_prioritizes_errors_and_rejects_wrong_values() -> None:
    collector = RuleResultCollector()
    collector.add(EngineResult((RuleResult.errored("rule", "first"),)))
    collector.add(EngineResult((RuleResult.errored("rule", "second"),)))
    assert collector.finish().results[0].error == "first; second"
    with pytest.raises(TypeError):
        collector.add(object())


def test_geometry_collector_aggregates_all_counts_but_bounds_findings() -> None:
    collector = GeometryResultCollector(maximum_findings=1)
    collector.add(
        GeometryChunkResult(
            2,
            2,
            Counter({"invalid_geometry": 2}),
            (
                GeometryFinding(0, (("invalid_geometry", "bad"),)),
                GeometryFinding(1, (("invalid_geometry", "bad"),)),
            ),
        )
    )

    result = collector.finish()

    assert result.feature_count == 2
    assert result.invalid_feature_count == 2
    assert result.issue_counts == {"invalid_geometry": 2}
    assert [finding.feature_index for finding in result.findings] == [0]
    with pytest.raises(TypeError):
        collector.add(object())
