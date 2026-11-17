from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest
from shapely.geometry import box

SCORING = Path(__file__).parents[2] / "tools" / "benchmark" / "scoring.py"


@pytest.fixture
def scoring(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location("benchmark_scoring", SCORING)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Its dataclasses look themselves up in sys.modules.
    monkeypatch.setitem(sys.modules, "benchmark_scoring", module)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class Defect:
    defect_type: str
    feature_index: int
    related_index: int = -1


def by_code(finding: object) -> str | None:
    codes = {"GEO-A": "a", "GEO-B": "b", "TOP-OVER": "overshoot", "TOP-GAP": "gap"}
    return codes.get(finding.code)  # type: ignore[attr-defined]


# Two 10 x 10 squares 100 units apart; feature indices 0 and 1.
SQUARES = [box(0, 0, 10, 10), box(110, 0, 120, 10)]


def test_wilson_known_values(scoring: ModuleType) -> None:
    low, high = scoring.wilson(100, 100)
    assert low == pytest.approx(0.963, abs=5e-4)
    assert high == 1.0
    low, high = scoring.wilson(0, 10)
    assert low == 0.0
    assert high == pytest.approx(0.2775, abs=5e-4)
    low, high = scoring.wilson(5, 10)
    assert (low, high) == (pytest.approx(0.2366, abs=5e-4), pytest.approx(0.7634, abs=5e-4))
    assert scoring.wilson(0, 0) == (0.0, 1.0)


def test_one_finding_never_scores_two_defects(scoring: ModuleType) -> None:
    # Two defects share feature 1; a single finding naming it can satisfy only one.
    defects = [Defect("a", 1), Defect("a", 1, 2)]
    findings = [scoring.Finding("GEO-A", "", frozenset({1}))]

    matched = scoring.match(defects, findings, by_code)

    assert len(matched) == 1
    assert sorted(matched.values()) == [0]


def test_one_defect_never_takes_two_findings(scoring: ModuleType) -> None:
    defects = [Defect("a", 1)]
    findings = [scoring.Finding("GEO-A", "", frozenset({1}))] * 2

    matched = scoring.match(defects, findings, by_code)
    split = scoring.classify(defects, findings, matched.values(), by_code)

    assert len(matched) == 1
    assert split.fp_defects == {"a": 1}


def test_matching_is_maximal_whatever_the_order(scoring: ModuleType) -> None:
    # Greedy would give finding 0 to defect 0 and leave defect 1 unmatched.
    defects = [Defect("a", 1, 2), Defect("a", 1)]
    findings = [
        scoring.Finding("GEO-A", "", frozenset({1})),
        scoring.Finding("GEO-A", "", frozenset({2})),
    ]

    matched = scoring.match(defects, findings, by_code)

    assert matched == {0: 1, 1: 0}


def test_type_must_agree_to_match(scoring: ModuleType) -> None:
    defects = [Defect("a", 1)]
    findings = [scoring.Finding("GEO-B", "", frozenset({1}))]

    assert scoring.match(defects, findings, by_code) == {}


def test_collateral_versus_false_positive(scoring: ModuleType) -> None:
    defects = [Defect("undershoot", 1), Defect("duplicate_segment_full", 5, 6)]
    findings = [
        # Allowed pair, on a defect feature: collateral of the undershoot.
        scoring.Finding("TOP-OVER", "", frozenset({0, 1})),
        # Allowed raw-code pair: collateral of the duplicate segment.
        scoring.Finding("TOP-NO-DUPLICATE", "", frozenset({5, 6})),
        # Allowed pair but on a clean feature: false positive.
        scoring.Finding("TOP-OVER", "", frozenset({9})),
        # On a defect feature but not an allowed pair: false positive.
        scoring.Finding("GEO-B", "", frozenset({1})),
        # Maps to no type and not allowed: unattributed.
        scoring.Finding("TOP-NO-GAP", "", frozenset()),
    ]

    split = scoring.classify(defects, findings, (), by_code)

    assert split.collateral == {"undershoot": 1, "duplicate_segment_full": 1}
    assert split.fp_defects == {"overshoot": 1, "b": 1}
    assert split.unattributed == {"TOP-NO-GAP": 1}


def test_new_collateral_pairs_are_allowed(scoring: ModuleType) -> None:
    defects = [Defect("self_intersection", 0), Defect("unnoded_t_junction", 1, 2)]
    findings = [
        scoring.Finding("TOP-NO-GAP", "", frozenset(), "POINT (10.2 5)"),
        scoring.Finding("ROAD-UNNODED_INTERSECTION", "", frozenset({1, 2})),
    ]

    split = scoring.classify(defects, findings, (), by_code, geometries=SQUARES + [box(0, 0, 1, 1)])

    assert split.collateral == {"self_intersection": 1, "unnoded_t_junction": 1}


def test_featureless_finding_matches_by_location(scoring: ModuleType) -> None:
    defects = [Defect("gap", 0), Defect("gap", 1)]
    findings = [
        # 0.4 units outside square 1: inside its 0.5 buffer.
        scoring.Finding("TOP-GAP", "", frozenset(), "POINT (120.4 5)"),
        # 0.6 units outside square 0: outside the buffer.
        scoring.Finding("TOP-GAP", "", frozenset(), "POINT (-0.6 5)"),
    ]

    matched = scoring.match(defects, findings, by_code, SQUARES)

    assert matched == {1: 0}


def test_location_needs_geometries(scoring: ModuleType) -> None:
    defects = [Defect("gap", 0)]
    findings = [scoring.Finding("TOP-GAP", "", frozenset(), "POINT (5 5)")]

    assert scoring.match(defects, findings, by_code) == {}


def test_feature_index_wins_over_location(scoring: ModuleType) -> None:
    # The finding sits on square 0 but names feature 1: features decide, not location.
    defects = [Defect("a", 0)]
    findings = [scoring.Finding("GEO-A", "", frozenset({1}), "POINT (5 5)")]

    assert scoring.match(defects, findings, by_code, SQUARES) == {}


def test_location_collateral_versus_false_positive(scoring: ModuleType) -> None:
    defects = [Defect("self_intersection", 0)]
    findings = [
        scoring.Finding("TOP-NO-GAP", "", frozenset(), "POINT (5 5)"),
        scoring.Finding("TOP-NO-GAP", "", frozenset(), "POINT (60 5)"),
    ]

    split = scoring.classify(defects, findings, (), by_code, geometries=SQUARES)

    assert split.collateral == {"self_intersection": 1}
    assert split.unattributed == {"TOP-NO-GAP": 1}


def test_scored_limits_false_positives_to_the_profile_types(scoring: ModuleType) -> None:
    findings = [
        scoring.Finding("GEO-A", "", frozenset({7})),
        scoring.Finding("GEO-B", "", frozenset({7})),
    ]

    split = scoring.classify([], findings, (), by_code, scored=frozenset({"a"}))

    assert split.fp_defects == {"a": 1}
    assert split.unattributed == {"GEO-B": 1}


def test_baseline_subtraction_is_by_code_and_location(scoring: ModuleType) -> None:
    end = scoring.Finding("TOP-NO-DANGLES", "Road end", frozenset({3}), "POINT (0 0)")
    renumbered = scoring.Finding("TOP-NO-DANGLES", "Road end", frozenset({2}), "POINT (0 0)")
    elsewhere = scoring.Finding("TOP-NO-DANGLES", "Road end", frozenset({3}), "POINT (1 0)")

    kept = scoring.subtract_baseline([renumbered, renumbered, elsewhere], [end])

    # One baseline finding removes one occurrence, whatever its feature index.
    assert kept == [renumbered, elsewhere]
