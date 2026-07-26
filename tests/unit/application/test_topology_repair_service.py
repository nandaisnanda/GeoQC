"""Tests for the stateful repair session and undo engine."""

from collections.abc import Sequence

import pytest

from geoqc.application.services.topology_repair import RepairSession, UndoEngine
from geoqc.domain.models.topology_repair import (
    CoverageRepairResult,
    FeatureRepairResult,
    GeometryRepairResult,
    RepairConfig,
    RepairMetrics,
    RepairReport,
    RepairStatus,
)


class _StubRepairer:
    """Coverage repairer that uppercases each WKT and records its calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def repair_coverage(self, wkts: Sequence[str], config: RepairConfig) -> CoverageRepairResult:
        self.calls.append(tuple(wkts))
        after = tuple(wkt.upper() for wkt in wkts)
        results = tuple(
            FeatureRepairResult(
                index,
                GeometryRepairResult(
                    geometry_type="Polygon",
                    status=RepairStatus.REPAIRED,
                    before_wkt=before,
                    after_wkt=before.upper(),
                    actions=(),
                    metrics=RepairMetrics(1.0, 1.0, 4, 4, 0.0),
                ),
            )
            for index, before in enumerate(wkts)
        )
        return CoverageRepairResult(tuple(wkts), after, RepairReport(results))


def test_undo_engine_tracks_and_restores_states() -> None:
    """The undo engine is a LIFO stack of restorable states."""
    engine = UndoEngine()
    assert not engine.can_undo

    engine.push(["a"])
    engine.push(["b", "c"])
    assert engine.depth == 2
    assert engine.undo() == ("b", "c")
    assert engine.undo() == ("a",)
    assert not engine.can_undo


def test_undo_engine_raises_when_empty() -> None:
    """Undoing with no history is a caller error."""
    with pytest.raises(IndexError, match="nothing to undo"):
        UndoEngine().undo()


def test_preview_does_not_mutate_working_set() -> None:
    """Preview computes a report without changing the session state."""
    session = RepairSession(["a", "b"], _StubRepairer())

    report = session.preview()

    assert report.total == 2
    assert session.geometries == ("a", "b")
    assert not session.can_undo


def test_apply_commits_and_undo_reverts() -> None:
    """Apply mutates state and records an undo point; undo reverses it."""
    session = RepairSession(["a", "b"], _StubRepairer())

    result = session.apply()

    assert result.after_wkt == ("A", "B")
    assert session.geometries == ("A", "B")
    assert session.can_undo
    assert session.undo_depth == 1

    session.undo()
    assert session.geometries == ("a", "b")
    assert not session.can_undo


def test_repeated_apply_is_fully_reversible() -> None:
    """A no-op apply does not create a misleading undo point."""
    session = RepairSession(["a"], _StubRepairer(), RepairConfig())

    session.apply()
    session.apply()
    assert session.geometries == ("A",)
    assert session.undo_depth == 1

    session.undo()
    assert session.geometries == ("a",)


def test_apply_reuses_preview_candidate() -> None:
    """Apply commits the exact candidate that the user previewed."""
    repairer = _StubRepairer()
    session = RepairSession(["a"], repairer)

    candidate = session.preview_result()
    applied = session.apply()

    assert candidate is applied
    assert repairer.calls == [("a",)]
