from geoqc.application.benchmarking import (
    BenchmarkContext,
    BenchmarkMetrics,
    BenchmarkReport,
    NoOpBenchmarkRecorder,
)


def metric(source: str = "roads.gpkg", runtime: float = 2.0) -> BenchmarkMetrics:
    return BenchmarkMetrics(
        source=source,
        runtime_seconds=runtime,
        cpu_time_seconds=1.0,
        cpu_usage_percent=50.0,
        memory_usage_bytes=100,
        peak_memory_bytes=1_000,
        feature_count=10,
        geometry_count=10,
        rule_count=2,
        engine="shapely",
        chunk_size=128,
        worker_count=2,
    )


def test_report_aggregates_records() -> None:
    report = BenchmarkReport((metric(), metric("buildings.gpkg", 3.0)))

    assert report.summary.audit_count == 2
    assert report.summary.runtime_seconds == 5.0
    assert report.summary.feature_count == 20
    assert report.summary.peak_memory_bytes == 1_000
    assert report.to_dict()["schema_version"] == "1.0"


def test_noop_recorder_does_not_call_describer() -> None:
    described = False

    def describe(value: int) -> tuple[int, int, str]:
        nonlocal described
        described = True
        return value, value, "engine"

    value, metrics = NoOpBenchmarkRecorder().measure(
        lambda: 7,
        BenchmarkContext("source", chunk_size=1, worker_count=1),
        describe,
    )

    assert value == 7
    assert metrics is None
    assert described is False
