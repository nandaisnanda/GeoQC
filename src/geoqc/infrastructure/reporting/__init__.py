"""Reporting adapters."""

from typing import TYPE_CHECKING

from geoqc.infrastructure.reporting.benchmark_report import (
    BenchmarkFormat,
    infer_benchmark_format,
    render_html,
    render_json,
    render_markdown,
    write_benchmark_report,
)

if TYPE_CHECKING:
    from geoqc.infrastructure.reporting.html_report import HtmlReportRenderer
    from geoqc.infrastructure.reporting.interactive_map import InteractiveMapRenderer

__all__ = [
    "BenchmarkFormat",
    "HtmlReportRenderer",
    "InteractiveMapRenderer",
    "infer_benchmark_format",
    "render_html",
    "render_json",
    "render_markdown",
    "write_benchmark_report",
]


def __getattr__(name: str) -> object:
    """Lazily import renderers that need the optional ``report`` extra.

    Keeps ``BenchmarkFormat``/``write_benchmark_report`` (used unconditionally
    by the CLI) importable without jinja2/folium installed.
    """
    if name == "HtmlReportRenderer":
        from geoqc.infrastructure.reporting.html_report import HtmlReportRenderer

        return HtmlReportRenderer
    if name == "InteractiveMapRenderer":
        from geoqc.infrastructure.reporting.interactive_map import InteractiveMapRenderer

        return InteractiveMapRenderer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
