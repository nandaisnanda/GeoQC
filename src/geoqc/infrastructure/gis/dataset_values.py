"""Dataset values for the canonical dataset workflow."""

from collections.abc import Mapping
from math import isnan

import geopandas as gpd  # type: ignore[import-untyped]
import pandas as pd
import shapely
from shapely.geometry.base import BaseGeometry

from geoqc.domain.models import (
    IssueGeometryKind,
)


def _kind(geometry: BaseGeometry) -> IssueGeometryKind:
    dimensions = shapely.get_dimensions(geometry)
    if dimensions >= 2:
        return IssueGeometryKind.POLYGON
    if dimensions == 1:
        return IssueGeometryKind.LINE
    return IssueGeometryKind.POINT


def _wkt(geometry: BaseGeometry) -> str:
    return str(shapely.to_wkt(geometry, rounding_precision=-1))


def _feature_attributes(
    frame: gpd.GeoDataFrame,
) -> tuple[Mapping[str, str | int | float | bool | None], ...]:
    columns = [column for column in frame.columns if column != frame.geometry.name]
    records: list[Mapping[str, str | int | float | bool | None]] = []
    for raw in frame[columns].to_dict(orient="records"):
        records.append({str(key): _attribute_value(value) for key, value in raw.items()})
    return tuple(records)


def _attribute_value(value: object) -> str | int | float | bool | None:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and isnan(value):
            return None
        return value
    item = getattr(value, "item", None)
    if callable(item):
        normalized = item()
        if isinstance(normalized, (str, int, float, bool)):
            return normalized
    return str(value)
