from collections.abc import Iterator

from geoqc.application.benchmarking import BenchmarkContext
from geoqc.infrastructure.benchmarking import ProcessBenchmarkRecorder, process_memory


def values(*items: float) -> Iterator[float]:
    yield from items


def test_process_recorder_calculates_metrics_from_snapshots() -> None:
    wall = values(10.0, 12.0)
    cpu = values(4.0, 5.0)
    memory = iter(((100, 500), (160, 700)))
    recorder = ProcessBenchmarkRecorder(
        wall_clock=lambda: next(wall),
        cpu_clock=lambda: next(cpu),
        memory_probe=lambda: next(memory),
    )

    value, result = recorder.measure(
        lambda: "result",
        BenchmarkContext("roads.gpkg", chunk_size=64, worker_count=3, rule_count=4),
        lambda _: (12, 11, "shapely"),
    )

    assert value == "result"
    assert result.runtime_seconds == 2.0
    assert result.cpu_usage_percent == 50.0
    assert result.memory_usage_bytes == 60
    assert result.peak_memory_bytes == 700
    assert result.geometry_count == 11


def test_process_memory_returns_non_negative_values() -> None:
    current, peak = process_memory()

    assert current >= 0
    assert peak >= current
