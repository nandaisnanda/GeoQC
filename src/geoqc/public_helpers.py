"""Shared validation helpers for the public convenience API."""

import shapely
from shapely.geometry.base import BaseGeometry


def require_geometry(geometry: BaseGeometry) -> BaseGeometry:
    if not isinstance(geometry, BaseGeometry):
        raise TypeError("geometry must be a Shapely BaseGeometry")
    return geometry


def to_wkt(geometry: BaseGeometry) -> str:
    return str(shapely.to_wkt(geometry, rounding_precision=-1))
