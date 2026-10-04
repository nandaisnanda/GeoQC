"""Shared Shapely serialization helpers for spatial intelligence."""

from collections.abc import Sequence

import shapely
from shapely.geometry.base import BaseGeometry


def _loads(wkts: Sequence[str]) -> list[BaseGeometry]:
    return [shapely.from_wkt(value) for value in wkts]


def _wkt(geometry: BaseGeometry) -> str:
    return str(shapely.to_wkt(geometry, rounding_precision=-1))
