"""Shared Shapely serialization helpers for spatial intelligence."""

from collections.abc import Sequence

import numpy as np
import shapely
from shapely.geometry.base import BaseGeometry


def _loads(wkts: Sequence[str]) -> list[BaseGeometry]:
    return [shapely.from_wkt(value) for value in wkts]


def _wkt(geometry: BaseGeometry) -> str:
    return str(shapely.to_wkt(geometry, rounding_precision=-1))


def _has_finite_coordinates(geometry: BaseGeometry) -> bool:
    """Return False for NaN or infinite coordinates.

    GEOS predicates raise on them and ``buffer`` can crash the interpreter. The
    geometry check reports such features as invalid, so cross-feature checks skip
    them instead of comparing them.
    """
    return bool(np.isfinite(shapely.get_coordinates(geometry)).all())


def _safe_buffer(geometry: BaseGeometry, distance: float) -> BaseGeometry | None:
    """Buffer a finite geometry, or return None when GEOS cannot.

    Coordinates near the float limit overflow inside ``buffer``: GEOS either
    raises or returns NaN coordinates that make the next predicate raise.
    """
    if not _has_finite_coordinates(geometry):
        return None
    try:
        buffered = geometry.buffer(distance)
    except shapely.errors.GEOSException:
        return None
    return buffered if _has_finite_coordinates(buffered) else None
