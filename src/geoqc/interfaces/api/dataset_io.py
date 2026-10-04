"""Dataset reading and GeoJSON conversion at the HTTP boundary."""

import json
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import pyogrio  # type: ignore[import-untyped]
import shapely
from fastapi import HTTPException
from shapely.geometry import GeometryCollection
from shapely.geometry.base import BaseGeometry

from geoqc.interfaces.api.settings import MAX_REPAIR_FEATURES as _MAX_REPAIR_FEATURES


def _read_frame(dataset_path: Path, layer: str | None) -> gpd.GeoDataFrame:
    """Read a bounded dataset while retaining attributes, index, and CRS."""
    frame = pyogrio.read_dataframe(dataset_path, layer=layer)
    if len(frame) > _MAX_REPAIR_FEATURES:
        raise HTTPException(
            status_code=413,
            detail=f"Repair is limited to {_MAX_REPAIR_FEATURES:,} features per dataset.",
        )
    return frame


def _frame_geometries(frame: gpd.GeoDataFrame) -> list[BaseGeometry]:
    """Return Shapely geometries, representing missing values as empty geometry."""
    empty = GeometryCollection()
    return [geometry if geometry is not None else empty for geometry in frame.geometry]


def _frame_geojson(frame: gpd.GeoDataFrame, wkts: tuple[str, ...]) -> str:
    """Serialize a geometry snapshot without discarding source attributes or CRS."""
    if len(frame) != len(wkts):
        raise ValueError("geometry snapshot length does not match the source frame")
    snapshot = frame.copy()
    snapshot.geometry = [shapely.from_wkt(wkt) for wkt in wkts]
    if snapshot.crs is not None:
        snapshot = snapshot.to_crs("EPSG:4326")
    geometry_name = snapshot.geometry.name
    features: list[dict[str, object]] = []
    for feature_id, (_, row) in enumerate(snapshot.iterrows()):
        properties = {
            str(name): _json_value(value) for name, value in row.items() if name != geometry_name
        }
        geometry = row[geometry_name]
        features.append(
            {
                "type": "Feature",
                "id": str(feature_id),
                "properties": properties,
                "geometry": shapely.geometry.mapping(geometry),
            }
        )
    return json.dumps({"type": "FeatureCollection", "features": features})


def _json_value(value: object) -> object:
    """Convert scalar dataframe values into strict JSON-compatible values."""
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
