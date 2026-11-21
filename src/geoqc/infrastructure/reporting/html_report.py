"""Jinja2 adapter for self-contained HTML quality reports."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from geoqc.domain.models import QualityReport
from geoqc.infrastructure.reporting.interactive_map import InteractiveMapRenderer


class HtmlReportRenderer:
    """Render normalized quality data as a modern standalone HTML document."""

    def __init__(self, map_renderer: InteractiveMapRenderer | None = None) -> None:
        self._environment = Environment(
            loader=PackageLoader("geoqc.infrastructure.reporting", "templates"),
            autoescape=select_autoescape(enabled_extensions=("html", "xml"), default=True),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._map_renderer = map_renderer or InteractiveMapRenderer()

    def render(
        self,
        report: QualityReport,
        *,
        impact: Mapping[str, Any] | None = None,
        notice: str | None = None,
    ) -> str:
        """Render a report to an HTML string, with optional impact section and score notice."""
        template = self._environment.get_template("quality_report.html")
        return template.render(
            report=report,
            map_html=self._map_renderer.render(report),
            impact=impact,
            notice=notice,
        )

    def write(
        self,
        report: QualityReport,
        destination: str | Path,
        *,
        impact: Mapping[str, Any] | None = None,
        notice: str | None = None,
    ) -> Path:
        """Render a report and write it as UTF-8, creating parent directories."""
        output_path = Path(destination)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self.render(report, impact=impact, notice=notice), encoding="utf-8")
        return output_path
