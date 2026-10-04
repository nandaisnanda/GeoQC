"""Public geometry validation and repair convenience functions."""

from collections.abc import Sequence

from shapely.geometry.base import BaseGeometry

from geoqc.application.services.topology_repair import RepairSession as RepairSession
from geoqc.domain.models import (
    CoverageRepairResult,
    GeometryRepairResult,
    GeometryValidationResult,
    RepairConfig,
)
from geoqc.infrastructure.gis.shapely_geometry_validator import ShapelyGeometryValidator
from geoqc.infrastructure.gis.shapely_topology_repairer import ShapelyTopologyRepairer
from geoqc.public_helpers import require_geometry, to_wkt

_geometry_validator = ShapelyGeometryValidator()
_topology_repairer = ShapelyTopologyRepairer(_geometry_validator)


def validate_geometry(geometry: BaseGeometry) -> GeometryValidationResult:
    """Validate one Shapely geometry for topology and duplicate-vertex issues.

    Args:
        geometry: Any Shapely geometry instance.

    Returns:
        An immutable result containing the geometry type and detected issues.

    Raises:
        TypeError: If ``geometry`` is not a Shapely geometry.
    """
    return _geometry_validator.validate(geometry)


def repair_geometry(
    geometry: BaseGeometry, config: RepairConfig | None = None
) -> GeometryRepairResult:
    """Repair the intrinsic topology of one Shapely geometry, minimally.

    Fixes self-intersections, invalid rings, duplicate vertices, and degenerate
    slivers while changing the original shape as little as possible. The result
    stores both the original and repaired geometry as WKT.

    Args:
        geometry: Any Shapely geometry instance.
        config: Optional thresholds; sensible conservative defaults are used.

    Returns:
        A reversible, reportable repair result.

    Raises:
        TypeError: If ``geometry`` is not a Shapely geometry.
    """
    if not isinstance(geometry, BaseGeometry):
        raise TypeError("geometry must be a Shapely BaseGeometry")
    return _topology_repairer.repair(to_wkt(geometry), config or RepairConfig())


def repair_geometries(
    geometries: Sequence[BaseGeometry], config: RepairConfig | None = None
) -> CoverageRepairResult:
    """Repair a set of geometries as one coverage in a single pass.

    Each geometry's intrinsic defects are fixed first, then cross-feature
    overlaps are erased (earlier features keep disputed area) and enclosed gaps
    below the configured area are filled into the neighbour with the longest
    shared boundary.

    Args:
        geometries: Shapely geometries forming one topological coverage.
        config: Optional thresholds; sensible conservative defaults are used.

    Returns:
        Before/after WKT for every feature and an aggregate repair report.

    Raises:
        TypeError: If any element is not a Shapely geometry.
    """
    wkts = [to_wkt(require_geometry(geometry)) for geometry in geometries]
    return _topology_repairer.repair_coverage(wkts, config or RepairConfig())


def repair_geometries_safely(geometries: Sequence[BaseGeometry]) -> CoverageRepairResult:
    """Apply only shape-preserving duplicate-vertex cleanup.

    Ambiguous operations such as invalid-geometry reconstruction, sliver
    removal, overlap resolution, and gap filling remain disabled. This is the
    appropriate default for unattended jobs and future QGIS "fix safe" UI.
    """
    return repair_geometries(
        geometries,
        RepairConfig(
            fix_invalid=False,
            remove_slivers=False,
            resolve_overlaps=False,
            fill_gaps=False,
            max_shape_shift=0.0,
            max_relative_area_change=0.0,
        ),
    )


def open_repair_session(
    geometries: Sequence[BaseGeometry], config: RepairConfig | None = None
) -> RepairSession:
    """Create a stateful repair session supporting preview, apply, and undo.

    Args:
        geometries: Shapely geometries forming one topological coverage.
        config: Optional thresholds; sensible conservative defaults are used.

    Returns:
        A session whose ``preview``/``apply``/``undo`` operate on WKT snapshots.

    Raises:
        TypeError: If any element is not a Shapely geometry.
    """
    wkts = [to_wkt(require_geometry(geometry)) for geometry in geometries]
    return RepairSession(wkts, _topology_repairer, config)
