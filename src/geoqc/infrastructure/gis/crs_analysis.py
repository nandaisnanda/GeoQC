"""CRS safety analysis for quality workflows."""

from collections.abc import Sequence

import shapely
from pyproj import CRS
from shapely.geometry.base import BaseGeometry

from geoqc.domain.models import CrsGuardResult, CrsUnitStatus


def assess_crs(crs: str | None, geometries: Sequence[BaseGeometry] = ()) -> CrsGuardResult:
    """Explain whether distance/area tolerances are safe for a CRS."""
    if crs is None or not str(crs).strip():
        return CrsGuardResult(
            None,
            CrsUnitStatus.UNKNOWN,
            None,
            False,
            "CRS is unknown; distance and area thresholds cannot be interpreted safely.",
        )
    try:
        parsed = CRS.from_user_input(crs)
    except Exception:
        return CrsGuardResult(
            str(crs),
            CrsUnitStatus.UNKNOWN,
            None,
            False,
            "CRS could not be parsed; verify the layer metadata before using tolerances.",
        )
    axes = parsed.axis_info
    unit = axes[0].unit_name if axes else None
    angular = bool(parsed.is_geographic)
    suggestion = _suggest_utm(geometries) if angular else None
    if angular:
        return CrsGuardResult(
            parsed.to_string(),
            CrsUnitStatus.WARNING,
            unit,
            True,
            "CRS uses angular units; distance and area tolerances are not metres.",
            suggestion,
        )
    return CrsGuardResult(
        parsed.to_string(),
        CrsUnitStatus.SAFE,
        unit,
        False,
        f"CRS uses projected {unit or 'linear'} units.",
    )


def _suggest_utm(geometries: Sequence[BaseGeometry]) -> str | None:
    non_empty = [item for item in geometries if not item.is_empty]
    if not non_empty:
        return None
    center = shapely.union_all(non_empty).centroid
    if not (-180 <= center.x <= 180 and -90 <= center.y <= 90):
        return None
    zone = min(60, max(1, int((center.x + 180) // 6) + 1))
    return f"EPSG:{32600 + zone if center.y >= 0 else 32700 + zone}"
