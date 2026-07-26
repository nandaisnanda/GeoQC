import json
from pathlib import Path

import pytest

from geoqc.application.benchmarking import BenchmarkMetrics, BenchmarkReport
from geoqc.infrastructure.reporting import (
    BenchmarkFormat,
    infer_benchmark_format,
    render_html,
    render_json,
    render_markdown,
    write_benchmark_report,
)


@pytest.fixture
def report() -> BenchmarkReport:
    return BenchmarkReport(
        (
            BenchmarkMetrics(
                source="roads.gpkg",
                runtime_seconds=1.25,
                cpu_time_seconds=1.0,
                cpu_usage_percent=80.0,
                memory_usage_bytes=1024,
                peak_memory_bytes=4096,
                feature_count=20,
                geometry_count=20,
                rule_count=3,
                engine="shapely",
                chunk_size=256,
                worker_count=2,
            ),
        )
    )


def test_renderers_include_metrics_and_visualization(report: BenchmarkReport) -> None:
    payload = json.loads(render_json(report))
    markdown = render_markdown(report)
    html = render_html(report)

    assert payload["records"][0]["engine"] == "shapely"
    assert "xychart-beta" in markdown
    assert "Runtime (seconds)" in html
    assert 'class="fill"' in html


def test_writer_infers_format_and_replaces_file(tmp_path: Path, report: BenchmarkReport) -> None:
    destination = tmp_path / "nested" / "benchmark.json"

    write_benchmark_report(report, destination)

    assert infer_benchmark_format(destination) is BenchmarkFormat.JSON
    assert json.loads(destination.read_text(encoding="utf-8"))["summary"]["audit_count"] == 1


def test_unknown_suffix_is_rejected() -> None:
    with pytest.raises(ValueError, match="Benchmark output"):
        infer_benchmark_format(Path("benchmark.txt"))
