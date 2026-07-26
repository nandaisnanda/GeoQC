"""Stateful topology-repair use case with preview, apply, and undo.

The working set is a tuple of WKT strings; every ``apply`` snapshots the prior
state so any number of applies can be reversed. No GIS library is imported here
- all geometry work is delegated to a :class:`CoverageRepairer` port.
"""

from collections.abc import Sequence

from geoqc.application.ports.geometry_repair import CoverageRepairer
from geoqc.domain.models.topology_repair import (
    CoverageRepairResult,
    RepairConfig,
    RepairReport,
)


class UndoEngine:
    """LIFO history of coverage states, enabling stepwise undo of applies."""

    def __init__(self) -> None:
        self._history: list[tuple[str, ...]] = []

    def push(self, state: Sequence[str]) -> None:
        """Record a state that a later :meth:`undo` can restore."""
        self._history.append(tuple(state))

    @property
    def depth(self) -> int:
        """Number of states that can still be undone."""
        return len(self._history)

    @property
    def can_undo(self) -> bool:
        """Return whether at least one prior state is available."""
        return bool(self._history)

    def undo(self) -> tuple[str, ...]:
        """Pop and return the most recent state, restoring it."""
        if not self._history:
            raise IndexError("nothing to undo")
        return self._history.pop()


class RepairSession:
    """Mutable working set of geometries with preview/apply/undo semantics."""

    def __init__(
        self,
        wkts: Sequence[str],
        repairer: CoverageRepairer,
        config: RepairConfig | None = None,
    ) -> None:
        self._current: tuple[str, ...] = tuple(wkts)
        self._repairer = repairer
        self._config = config or RepairConfig()
        self._undo = UndoEngine()
        self._preview: CoverageRepairResult | None = None

    @property
    def geometries(self) -> tuple[str, ...]:
        """Current working-set geometries as WKT."""
        return self._current

    @property
    def can_undo(self) -> bool:
        """Return whether the last apply can be reversed."""
        return self._undo.can_undo

    @property
    def undo_depth(self) -> int:
        """Number of applies that can still be undone."""
        return self._undo.depth

    def preview(self) -> RepairReport:
        """Compute repairs against the current state without mutating it."""
        return self.preview_result().report

    def preview_result(self) -> CoverageRepairResult:
        """Return the complete candidate, including before/after geometries."""
        if self._preview is None or self._preview.before_wkt != self._current:
            self._preview = self._repairer.repair_coverage(self._current, self._config)
        return self._preview

    def apply(self) -> CoverageRepairResult:
        """Repair the current state, snapshot the prior state, and commit."""
        result = self.preview_result()
        if result.after_wkt != self._current:
            self._undo.push(self._current)
            self._current = result.after_wkt
        self._preview = None
        return result

    def undo(self) -> tuple[str, ...]:
        """Restore the working set to the state before the last apply."""
        self._current = self._undo.undo()
        self._preview = None
        return self._current
