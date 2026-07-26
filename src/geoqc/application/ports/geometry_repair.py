"""Outbound ports for intelligent topology repair.

Geometries cross this boundary as WKT so the application layer never imports a
GIS library; the infrastructure adapter is the only place Shapely is used.
"""

from collections.abc import Sequence
from typing import Protocol

from geoqc.domain.models.topology_repair import (
    CoverageRepairResult,
    GeometryRepairResult,
    RepairConfig,
)


class GeometryRepairer(Protocol):
    """Repair the intrinsic topology of a single geometry."""

    def repair(self, wkt: str, config: RepairConfig) -> GeometryRepairResult:
        """Return a reversible repair result for one WKT geometry."""
        ...


class CoverageRepairer(Protocol):
    """Repair a set of geometries as one topological coverage.

    Implementations first repair each geometry's intrinsic defects, then resolve
    cross-feature overlaps and fill enclosed gaps below the configured area.
    """

    def repair_coverage(self, wkts: Sequence[str], config: RepairConfig) -> CoverageRepairResult:
        """Return before/after WKT and a report for the whole coverage."""
        ...
