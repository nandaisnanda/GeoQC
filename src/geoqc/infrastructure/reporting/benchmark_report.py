"""Self-contained JSON, Markdown, and HTML benchmark reports."""

# ruff: noqa: E501 -- Embedded HTML/CSS remains readable as a self-contained template.

import html
import json
from enum import StrEnum
from pathlib import Path

from geoqc.application.benchmarking import BenchmarkMetrics, BenchmarkReport


class BenchmarkFormat(StrEnum):
    JSON = "json"
    MARKDOWN = "markdown"
    HTML = "html"


_SUFFIX_FORMATS = {
    ".json": BenchmarkFormat.JSON,
    ".md": BenchmarkFormat.MARKDOWN,
    ".markdown": BenchmarkFormat.MARKDOWN,
    ".html": BenchmarkFormat.HTML,
    ".htm": BenchmarkFormat.HTML,
}


def infer_benchmark_format(path: Path) -> BenchmarkFormat:
    """Infer a supported report format from a path suffix."""
    try:
        return _SUFFIX_FORMATS[path.suffix.casefold()]
    except KeyError as error:
        raise ValueError(
            "Benchmark output must end in .json, .md, .markdown, .html, or .htm"
        ) from error


def write_benchmark_report(
    report: BenchmarkReport,
    destination: Path,
    output_format: BenchmarkFormat | None = None,
) -> None:
    """Render and atomically replace one UTF-8 benchmark report."""
    selected = output_format or infer_benchmark_format(destination)
    renderers = {
        BenchmarkFormat.JSON: render_json,
        BenchmarkFormat.MARKDOWN: render_markdown,
        BenchmarkFormat.HTML: render_html,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(renderers[selected](report), encoding="utf-8")
    temporary.replace(destination)


def render_json(report: BenchmarkReport) -> str:
    return json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n"


def render_markdown(report: BenchmarkReport) -> str:
    summary = report.summary
    lines = [
        "# GeoQC Benchmark Report",
        "",
        "## Summary",
        "",
        f"- Audits: **{summary.audit_count}**",
        f"- Runtime: **{summary.runtime_seconds:.6f} s**",
        f"- Average CPU usage: **{summary.average_cpu_usage_percent:.2f}%**",
        f"- Peak memory: **{_bytes(summary.peak_memory_bytes)}**",
        f"- Features / geometries: **{summary.feature_count} / {summary.geometry_count}**",
        "",
        "## Runtime chart",
        "",
        "```mermaid",
        "xychart-beta",
        '    title "Runtime per audit (seconds)"',
        f"    x-axis [{', '.join(_mermaid_label(record.source) for record in report.records)}]",
        f"    bar [{', '.join(f'{record.runtime_seconds:.6f}' for record in report.records)}]",
        "```",
        "",
        "## Audit metrics",
        "",
        "| Source | Runtime (s) | CPU (%) | Memory delta | Peak memory | Features | "
        "Geometries | Rules | Engine | Chunk | Workers |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|",
    ]
    lines.extend(_markdown_row(record) for record in report.records)
    return "\n".join(lines) + "\n"


def render_html(report: BenchmarkReport) -> str:
    summary = report.summary
    runtime_chart = _html_chart(report.records, "runtime_seconds", "Runtime (seconds)")
    memory_chart = _html_chart(report.records, "peak_memory_bytes", "Peak memory (bytes)")
    rows = "".join(_html_row(record) for record in report.records)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>GeoQC Benchmark Report</title>
  <style>
    :root {{ color-scheme: light dark; --accent:#2563eb; --card:#f8fafc; --ink:#0f172a; }}
    * {{ box-sizing:border-box }} body {{ margin:0; font:14px system-ui,sans-serif; color:var(--ink); background:#eef2ff }}
    main {{ max-width:1200px; margin:auto; padding:32px }} h1,h2 {{ margin-top:0 }}
    .cards,.charts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:16px; margin:20px 0 }}
    .card,.chart,.table-wrap {{ background:white; border-radius:12px; padding:18px; box-shadow:0 2px 10px #0f172a18 }}
    .value {{ font-size:1.55rem; font-weight:700 }} .bars {{ display:grid; gap:10px }}
    .bar-label {{ display:flex; justify-content:space-between; gap:12px }}
    .track {{ height:12px; background:#dbeafe; border-radius:8px; overflow:hidden }}
    .fill {{ height:100%; background:var(--accent); min-width:1px }}
    .table-wrap {{ overflow:auto }} table {{ border-collapse:collapse; width:100% }}
    th,td {{ padding:9px 10px; border-bottom:1px solid #e2e8f0; text-align:right; white-space:nowrap }}
    th:first-child,td:first-child,th:nth-child(9),td:nth-child(9) {{ text-align:left }}
    @media (prefers-color-scheme:dark) {{ :root{{--card:#111827;--ink:#e5e7eb}} body{{background:#020617}} .card,.chart,.table-wrap{{background:#111827}} }}
  </style>
</head>
<body><main>
  <h1>GeoQC Benchmark Report</h1>
  <div class="cards">
    {_card("Audits", str(summary.audit_count))}
    {_card("Runtime", f"{summary.runtime_seconds:.3f} s")}
    {_card("Average CPU", f"{summary.average_cpu_usage_percent:.1f}%")}
    {_card("Peak memory", _bytes(summary.peak_memory_bytes))}
    {_card("Features", str(summary.feature_count))}
    {_card("Geometries", str(summary.geometry_count))}
  </div>
  <div class="charts">{runtime_chart}{memory_chart}</div>
  <h2>Audit metrics</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>Source</th><th>Runtime (s)</th><th>CPU (%)</th><th>Memory delta</th><th>Peak memory</th><th>Features</th><th>Geometries</th><th>Rules</th><th>Engine</th><th>Chunk</th><th>Workers</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
</main></body></html>
"""


def _markdown_row(record: BenchmarkMetrics) -> str:
    source = record.source.replace("|", "\\|")
    return (
        f"| {source} | {record.runtime_seconds:.6f} | {record.cpu_usage_percent:.2f} | "
        f"{_bytes(record.memory_usage_bytes)} | {_bytes(record.peak_memory_bytes)} | "
        f"{record.feature_count} | {record.geometry_count} | {record.rule_count} | "
        f"{record.engine} | {record.chunk_size} | {record.worker_count} |"
    )


def _html_row(record: BenchmarkMetrics) -> str:
    cells = (
        html.escape(record.source),
        f"{record.runtime_seconds:.6f}",
        f"{record.cpu_usage_percent:.2f}",
        _bytes(record.memory_usage_bytes),
        _bytes(record.peak_memory_bytes),
        str(record.feature_count),
        str(record.geometry_count),
        str(record.rule_count),
        html.escape(record.engine),
        str(record.chunk_size),
        str(record.worker_count),
    )
    return "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"


def _html_chart(records: tuple[BenchmarkMetrics, ...], attribute: str, title: str) -> str:
    values = [float(getattr(record, attribute)) for record in records]
    maximum = max(values, default=0.0)
    bars = []
    for record, value in zip(records, values, strict=True):
        width = value / maximum * 100.0 if maximum else 0.0
        label = html.escape(Path(record.source).name or record.source)
        bars.append(
            f'<div><div class="bar-label"><span>{label}</span><strong>{value:.3f}</strong></div>'
            f'<div class="track"><div class="fill" style="width:{width:.2f}%"></div></div></div>'
        )
    return f'<section class="chart"><h2>{html.escape(title)}</h2><div class="bars">{"".join(bars)}</div></section>'


def _card(label: str, value: str) -> str:
    return f'<div class="card"><div>{html.escape(label)}</div><div class="value">{html.escape(value)}</div></div>'


def _bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024.0 or unit == "TiB":
            return f"{amount:.2f} {unit}"
        amount /= 1024.0
    raise AssertionError("unreachable")


def _mermaid_label(source: str) -> str:
    label = (Path(source).name or source).replace('"', "'")
    return f'"{label}"'
