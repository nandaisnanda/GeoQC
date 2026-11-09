"""Geometry helpers shared by the Folium map renderers.

Private to ``geoqc.infrastructure.reporting``. Importing this module needs the
optional ``report`` extra, like the renderers that use it.
"""

from collections.abc import Iterable

import folium
import shapely
from shapely.geometry.base import BaseGeometry


def geojson_from_wkt(wkt: str) -> dict[str, object]:
    """Convert one WKT geometry to a GeoJSON geometry mapping."""
    return shapely.geometry.mapping(shapely.from_wkt(wkt))


def map_fitted_to(wkts: Iterable[str], *, control_scale: bool = False) -> folium.Map:
    """Build a Folium map centred on, and zoomed to, the extent of the geometries.

    An empty input gives a world view at zoom 2. ``control_scale`` adds the
    Leaflet scale bar.
    """
    geometries: list[BaseGeometry] = [shapely.from_wkt(value) for value in wkts]
    if not geometries:
        return folium.Map(location=[0, 0], zoom_start=2)
    bounds = shapely.union_all(geometries).bounds
    result = folium.Map(
        location=[(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2],
        control_scale=control_scale,
    )
    result.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
    return result
