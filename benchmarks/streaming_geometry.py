"""Simple manual benchmark comparing full-frame and streaming geometry audits."""

import argparse
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path

import geopandas as gpd

from geoqc.application.streaming.engine import StreamingEngine
from geoqc.application.streaming.geometry import GeometryResultCollector
from geoqc.application.streaming.models import DatasetSource, StreamingConfig
from geoqc.infrastructure.gis.shapely_geometry_validator import ShapelyGeometryValidator
from geoqc.infrastructure.gis.streaming import default_reader_registry
from geoqc.infrastructure.gis.streaming.geometry_processor import GeometryChunkProcessor


def measure(operation: Callable[[], object]) -> tuple[float, float]:
    tracemalloc.start()
    started = time.perf_counter()
    operation()
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return elapsed, peak / (1024 * 1024)


def legacy(path: Path) -> None:
    validator = ShapelyGeometryValidator()
    frame = gpd.read_file(path)
    for geometry in frame.geometry:
        validator.validate(geometry)


def streaming(path: Path, chunk_size: int) -> None:
    source = DatasetSource(path)
    StreamingEngine(
        default_reader_registry().resolve(source),
        GeometryChunkProcessor(ShapelyGeometryValidator()),
        GeometryResultCollector(maximum_findings=0),
        StreamingConfig(chunk_size=chunk_size),
    ).run(source)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--chunk-size", type=int, default=65_536)
    args = parser.parse_args()
    for name, operation in (
        ("legacy", lambda: legacy(args.dataset)),
        ("streaming", lambda: streaming(args.dataset, args.chunk_size)),
    ):
        elapsed, peak = measure(operation)
        print(f"{name:10} time={elapsed:8.3f}s peak_python_memory={peak:8.1f}MiB")


if __name__ == "__main__":
    main()
