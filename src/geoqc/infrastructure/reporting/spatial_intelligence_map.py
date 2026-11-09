"""Interactive visualizations for spatial intelligence results."""

from collections.abc import Iterable
from pathlib import Path

import folium
import shapely

from geoqc.domain.models.spatial_intelligence import (
    BoundarySnapResult,
    RoadNetworkReport,
    SmallPolygonReport,
)
from geoqc.infrastructure.reporting._folium_geometry import geojson_from_wkt, map_fitted_to


class SpatialIntelligenceMap:
    """Render before/after geometry and categorized findings with Folium."""

    def boundary_snap(self, report: BoundarySnapResult, output: str | Path) -> Path:
        result = map_fitted_to(item.before_wkt for item in report.features)
        for item in report.features:
            folium.GeoJson(
                geojson_from_wkt(item.before_wkt),
                style_function=lambda _: {"color": "#64748b", "dashArray": "5"},
                name="Before",
            ).add_to(result)
            folium.GeoJson(
                geojson_from_wkt(item.after_wkt),
                style_function=lambda _: {"color": "#16a34a", "fillOpacity": 0.2},
                tooltip=f"Feature {item.feature_index}: area Δ {item.area_delta:.6g}",
                name="After",
            ).add_to(result)
        return self._save(result, output)

    def roads(
        self, report: RoadNetworkReport, geometries_wkt: Iterable[str], output: str | Path
    ) -> Path:
        wkts = list(geometries_wkt)
        result = map_fitted_to(wkts)
        for value in wkts:
            folium.GeoJson(
                geojson_from_wkt(value), style_function=lambda _: {"color": "#334155"}
            ).add_to(result)
        colors = {
            "dead_end": "orange",
            "dangling_road": "red",
            "broken_connection": "purple",
            "duplicate_segment": "blue",
            "loop_error": "black",
        }
        for finding in report.findings:
            geometry = shapely.from_wkt(finding.location_wkt)
            location = [geometry.centroid.y, geometry.centroid.x]
            folium.CircleMarker(
                location,
                radius=6,
                color=colors[finding.issue_type.value],
                tooltip=f"{finding.issue_type.value}: {finding.message}",
            ).add_to(result)
        return self._save(result, output)

    def small_polygons(self, report: SmallPolygonReport, output: str | Path) -> Path:
        result = map_fitted_to(item.source_wkt for item in report.findings)
        colors = {"delete": "#dc2626", "merge": "#16a34a", "ignore": "#eab308"}
        for item in report.findings:
            folium.GeoJson(
                geojson_from_wkt(item.source_wkt),
                style_function=lambda _, color=colors[item.recommendation.value]: {
                    "color": color,
                    "fillOpacity": 0.35,
                },
                tooltip=f"{item.issue_type.value}: {item.recommendation.value}",
            ).add_to(result)
            if item.preview_wkt:
                folium.GeoJson(
                    geojson_from_wkt(item.preview_wkt),
                    style_function=lambda _: {"color": "#2563eb", "dashArray": "4"},
                    name="Merge preview",
                ).add_to(result)
        return self._save(result, output)

    @staticmethod
    def _save(map_: folium.Map, output: str | Path) -> Path:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        folium.LayerControl().add_to(map_)
        map_.save(str(path))
        return path
