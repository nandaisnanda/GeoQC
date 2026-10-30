"""CRS safety analysis for quality workflows."""

from collections.abc import Sequence
from functools import cache

import shapely
from pyproj import CRS
from pyproj.database import query_crs_info
from pyproj.enums import PJType
from pyproj.exceptions import CRSError
from shapely.geometry.base import BaseGeometry

from geoqc.domain.models import CrsGuardResult, CrsUnitStatus
from geoqc.infrastructure.gis.spatial_helpers import _is_valid


def assess_crs(crs: str | None, geometries: Sequence[BaseGeometry] = ()) -> CrsGuardResult:
    """Explain whether distance/area tolerances are safe for a CRS."""
    if crs is None or not str(crs).strip():
        hint, suggestion = _guess_missing_crs(geometries)
        return CrsGuardResult(
            None,
            CrsUnitStatus.UNKNOWN,
            None,
            False,
            "CRS is unknown; distance and area thresholds cannot be interpreted safely." + hint,
            suggestion,
        )
    try:
        parsed = CRS.from_user_input(crs)
    except CRSError:
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
    recognized = _recognize_indonesian(parsed)
    if angular:
        return CrsGuardResult(
            parsed.to_string(),
            CrsUnitStatus.WARNING,
            unit,
            True,
            "CRS uses angular units; distance and area tolerances are not metres." + recognized,
            suggestion,
        )
    return CrsGuardResult(
        parsed.to_string(),
        CrsUnitStatus.SAFE,
        unit,
        False,
        f"CRS uses projected {unit or 'linear'} units." + recognized,
    )


def _suggest_utm(geometries: Sequence[BaseGeometry]) -> str | None:
    # union_all is an overlay and raises on invalid input; NaN coordinates are invalid too.
    usable = [item for item in geometries if not item.is_empty and _is_valid(item)]
    if not usable:
        return None
    try:
        center = shapely.union_all(usable).centroid
    except shapely.errors.GEOSException:
        # Valid but extreme coordinates (about 1e300) can still fail inside GEOS.
        return None
    if center.is_empty or not (-180 <= center.x <= 180 and -90 <= center.y <= 90):
        return None
    zone = min(60, max(1, int((center.x + 180) // 6) + 1))
    return _epsg_by_name(f"WGS 84 / UTM zone {zone}{'N' if center.y >= 0 else 'S'}")


@cache
def _epsg_names() -> dict[str, str]:
    # Codes come from the bundled PROJ database so none are written by hand here.
    infos = query_crs_info(
        auth_name="EPSG", pj_types=[PJType.GEOGRAPHIC_2D_CRS, PJType.PROJECTED_CRS]
    )
    return {info.name: f"EPSG:{info.code}" for info in infos if not info.deprecated}


def _epsg_by_name(name: str) -> str | None:
    return _epsg_names().get(name)


@cache
def _indonesian_crs() -> dict[str, str]:
    """Map EPSG codes of SRGI2013, DGN95 and WGS 84 / UTM 46S-54S to their names."""
    wgs84_utm = {f"WGS 84 / UTM zone {zone}S" for zone in range(46, 55)}
    return {
        code: name
        for name, code in _epsg_names().items()
        if name.startswith(("SRGI2013", "DGN95")) or name in wgs84_utm
    }


def _recognize_indonesian(parsed: CRS) -> str:
    epsg = parsed.to_epsg()
    name = _indonesian_crs().get(f"EPSG:{epsg}") if epsg is not None else None
    return f" Recognized Indonesian CRS: {name} (EPSG:{epsg})." if name else ""


def _guess_missing_crs(geometries: Sequence[BaseGeometry]) -> tuple[str, str | None]:
    """Guess a CRS from coordinate ranges for the message only; never assign it."""
    usable = [item for item in geometries if not item.is_empty and _is_valid(item)]
    if not usable:
        return "", None
    min_x, min_y, max_x, max_y = shapely.total_bounds(usable)
    if min_x >= 94 and max_x <= 142 and min_y >= -11 and max_y <= 6:
        suggestion = _suggest_utm(usable)
        return (
            " Coordinates fall within Indonesia in degrees, so the data is probably "
            f"geographic: {_epsg_by_name('SRGI2013')} (SRGI2013) or "
            f"{_epsg_by_name('WGS 84')} (WGS 84). Suggested projected CRS: {suggestion}. "
            "Verify and define the CRS yourself; it was not assigned.",
            suggestion,
        )
    if max(abs(min_x), abs(max_x), abs(min_y), abs(max_y)) > 360:
        first = _epsg_by_name("WGS 84 / UTM zone 46S")
        last = _epsg_by_name("WGS 84 / UTM zone 54S")
        return (
            " Coordinates look like projected metres, but the zone is unknown. For "
            f"Indonesia check WGS 84 / UTM zone 46S-54S ({first} to {last}), "
            "SRGI2013 / UTM or DGN95 / Indonesia TM-3. Verify and define the CRS yourself; "
            "it was not assigned.",
            None,
        )
    return "", None
