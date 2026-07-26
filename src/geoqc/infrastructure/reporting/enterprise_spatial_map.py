"""Self-contained interactive maps for enterprise spatial reports."""

from collections.abc import Iterable
from pathlib import Path

import folium
import shapely
from shapely.geometry.base import BaseGeometry

from geoqc.domain.models.enterprise_spatial import (
    DatasetDifferenceReport,
    SpatialConflictReport,
    SpatialDuplicateReport,
)


def _geojson(value: str) -> dict[str, object]:
    return shapely.geometry.mapping(shapely.from_wkt(value))


def _map(values: Iterable[str]) -> folium.Map:
    geometries: list[BaseGeometry] = [shapely.from_wkt(value) for value in values]
    if not geometries:
        return folium.Map(location=[0, 0], zoom_start=2)
    bounds = shapely.union_all(geometries).bounds
    result = folium.Map(
        location=[(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2],
        control_scale=True,
    )
    result.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
    return result


class EnterpriseSpatialMap:
    """Render duplicate, difference, and conflict reports with togglable layers."""

    def duplicates(self, report: SpatialDuplicateReport, output: str | Path) -> Path:
        result = _map(value for pair in report.pairs for value in (pair.left_wkt, pair.right_wkt))
        for pair in report.pairs:
            tooltip = (
                f"Pair {pair.left_index}/{pair.right_index}: "
                f"{pair.similarity_percent:.2f}% similar"
            )
            for value, color, name in (
                (pair.left_wkt, "#2563eb", "Duplicate left"),
                (pair.right_wkt, "#dc2626", "Duplicate right"),
            ):
                folium.GeoJson(
                    _geojson(value),
                    name=name,
                    tooltip=tooltip,
                    style_function=lambda _, color=color: {
                        "color": color,
                        "weight": 3,
                        "fillOpacity": 0.25,
                    },
                ).add_to(result)
        return self._save(result, output)

    def differences(self, report: DatasetDifferenceReport, output: str | Path) -> Path:
        values = [
            value
            for item in report.differences
            for value in (item.left_wkt, item.right_wkt)
            if value is not None
        ]
        result = _map(values)
        colors = {
            "added": "#16a34a",
            "removed": "#dc2626",
            "modified": "#f59e0b",
            "unchanged": "#64748b",
        }
        for item in report.differences:
            for side, value in (("before", item.left_wkt), ("after", item.right_wkt)):
                if value is None:
                    continue
                folium.GeoJson(
                    _geojson(value),
                    name=f"{item.kind.value} · {side}",
                    tooltip=(
                        f"{item.kind.value}: "
                        f"{item.geometry_similarity_percent:.2f}% geometry match"
                    ),
                    style_function=lambda _, color=colors[item.kind.value], side=side: {
                        "color": color,
                        "dashArray": "5" if side == "before" else None,
                        "fillOpacity": 0.2,
                    },
                ).add_to(result)
        return self._save(result, output)

    def conflicts(self, report: SpatialConflictReport, output: str | Path) -> Path:
        result = _map(item.geometry_wkt for item in report.conflicts)
        for item in report.conflicts:
            color = "#991b1b" if item.severity_score >= 80 else "#f59e0b"
            folium.GeoJson(
                _geojson(item.geometry_wkt),
                name=item.conflict_type.value,
                tooltip=f"Severity {item.severity_score:.1f} · {item.message}",
                style_function=lambda _, color=color: {
                    "color": color,
                    "weight": 4,
                    "fillOpacity": 0.45,
                },
            ).add_to(result)
        return self._save(result, output)

    @staticmethod
    def _save(result: folium.Map, output: str | Path) -> Path:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        folium.LayerControl(collapsed=False).add_to(result)
        result.save(str(path))
        return path
