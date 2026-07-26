"""Folium adapter for interactive quality-issue maps."""

from html import escape
from json import dumps
from typing import cast

import folium
from branca.element import Element, Figure

from geoqc.domain.models import QualityReport, QualityReportIssue

_SEVERITY_COLORS = {
    "info": "#2563eb",
    "warning": "#b45309",
    "error": "#dc2626",
    "critical": "#881337",
}


class InteractiveMapRenderer:
    """Render geolocated report issues as an accessible Folium map."""

    def render(self, report: QualityReport) -> str | None:
        """Return embeddable map HTML, or ``None`` when no issue is geolocated."""
        located_issues = [
            (index, issue)
            for index, issue in enumerate(report.issues)
            if issue.map_location is not None
        ]
        if not located_issues:
            return None

        coordinates = [
            [issue.map_location.latitude, issue.map_location.longitude]
            for _, issue in located_issues
            if issue.map_location is not None
        ]
        quality_map = folium.Map(
            location=coordinates[0],
            zoom_start=15,
            tiles=None,
            control_scale=True,
            prefer_canvas=True,
        )
        folium.TileLayer(
            tiles="CartoDB positron",
            name="Light basemap",
            control=False,
        ).add_to(quality_map)

        marker_registry: dict[str, dict[str, object]] = {}
        for issue_index, issue in located_issues:
            point = issue.map_location
            if point is None:  # Narrowed above; retained for static type checkers.
                continue
            issue_id = f"issue-{issue_index}"
            color = _SEVERITY_COLORS[issue.severity.value]
            marker = folium.CircleMarker(
                location=[point.latitude, point.longitude],
                radius=9,
                color="#ffffff",
                weight=3,
                fill=True,
                fill_color=color,
                fill_opacity=1,
                tooltip=f"{escape(issue.code)} · {escape(issue.title)}",
                popup=folium.Popup(self._popup_html(issue, color), max_width=360),
            )
            marker.add_to(quality_map)
            marker_registry[issue_id] = {
                "lat": point.latitude,
                "lng": point.longitude,
                "marker": marker.get_name(),
            }

        if len(coordinates) > 1:
            quality_map.fit_bounds(coordinates, padding=(32, 32), max_zoom=16)

        self._add_focus_api(quality_map, marker_registry)
        return quality_map.get_root().render()

    @staticmethod
    def _popup_html(issue: QualityReportIssue, color: str) -> str:
        location = (
            f'<div style="color:#64748b;margin-top:6px">{escape(issue.location)}</div>'
            if issue.location is not None
            else ""
        )
        return f"""
        <article style="font:14px/1.5 Inter,system-ui,sans-serif;color:#14213d;width:280px">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:center">
            <strong style="font-size:15px">{escape(issue.title)}</strong>
            <span style="background:{color};color:white;border-radius:999px;padding:3px 8px;
                         font-size:10px;font-weight:800;text-transform:uppercase">
              {escape(issue.severity.value)}
            </span>
          </div>
          <div style="color:#64748b;margin-top:5px">
            {escape(issue.code)} · {escape(issue.category)}
          </div>
          {location}
          <p style="margin:12px 0 0">{escape(issue.description)}</p>
          <div style="border-top:1px solid #e2e8f0;margin-top:12px;padding-top:10px">
            <strong>Recommended action</strong><br>{escape(issue.recommendation)}
          </div>
        </article>
        """

    @staticmethod
    def _add_focus_api(
        quality_map: folium.Map,
        marker_registry: dict[str, dict[str, object]],
    ) -> None:
        map_name = quality_map.get_name()
        registry_json = dumps(marker_registry)
        root = cast(Figure, quality_map.get_root())
        root.script.add_child(
            Element(
                f"""
                const geoqcMarkers = {registry_json};
                window.GeoQCMap = {{
                  focusIssue: function(issueId) {{
                    const target = geoqcMarkers[issueId];
                    if (!target) return false;
                    {map_name}.flyTo([target.lat, target.lng], 17, {{duration: 0.7}});
                    window.setTimeout(function() {{
                      window[target.marker].openPopup();
                    }}, 500);
                    return true;
                  }}
                }};
                """
            )
        )
