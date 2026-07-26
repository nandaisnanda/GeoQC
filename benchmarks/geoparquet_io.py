"""Compare bounded scans for GeoPackage, GeoJSON, Shapefile, and GeoParquet."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
import tracemalloc
from dataclasses import asdict, dataclass
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

from geoqc.application.streaming import DatasetSource, ScanOptions, ScanPredicate
from geoqc.infrastructure.gis.streaming import default_reader_registry


@dataclass(frozen=True)
class Measurement:
    format: str
    scenario: str
    rows: int
    seconds: float
    rows_per_second: float
    peak_memory_mib: float
    storage_mib: float


def _fixture(rows: int) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "id": range(rows),
            "category": [f"class-{index % 10}" for index in range(rows)],
            "payload": [f"attribute-{index % 1000}" for index in range(rows)],
        },
        geometry=[Point(index % 1000, index // 1000) for index in range(rows)],
        crs="EPSG:4326",
    )


def _write_formats(frame: gpd.GeoDataFrame, directory: Path) -> dict[str, Path]:
    paths = {
        "GeoPackage": directory / "fixture.gpkg",
        "GeoJSON": directory / "fixture.geojson",
        "Shapefile": directory / "fixture.shp",
        "GeoParquet": directory / "fixture.parquet",
    }
    frame.to_file(paths["GeoPackage"], driver="GPKG", engine="pyogrio")
    frame.to_file(paths["GeoJSON"], driver="GeoJSON", engine="pyogrio")
    frame.to_file(paths["Shapefile"], driver="ESRI Shapefile", engine="pyogrio")
    frame.to_parquet(paths["GeoParquet"], compression="zstd", row_group_size=65_536)
    return paths


def _storage_size(path: Path) -> int:
    if path.suffix.casefold() != ".shp":
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.parent.glob(f"{path.stem}.*"))


def _measure(label: str, path: Path, scenario: str, source: DatasetSource) -> Measurement:
    reader = default_reader_registry().resolve(source)
    tracemalloc.start()
    started = time.perf_counter()
    rows = sum(chunk.size for chunk in reader.iter_chunks(source, 65_536))
    seconds = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return Measurement(
        label,
        scenario,
        rows,
        seconds,
        rows / seconds if seconds else float("inf"),
        peak / 1024**2,
        _storage_size(path) / 1024**2,
    )


def run(rows: int) -> list[Measurement]:
    with tempfile.TemporaryDirectory(prefix="geoqc-geoparquet-") as raw:
        paths = _write_formats(_fixture(rows), Path(raw))
        results = [
            _measure(label, path, "full-scan", DatasetSource(path)) for label, path in paths.items()
        ]
        parquet_path = paths["GeoParquet"]
        results.append(
            _measure(
                "GeoParquet",
                parquet_path,
                "projected-filtered",
                DatasetSource(
                    parquet_path,
                    scan=ScanOptions(
                        columns=("id",),
                        include_geometry=False,
                        predicates=(ScanPredicate("category", "==", "class-1"),),
                    ),
                ),
            )
        )
        return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=250_000)
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()
    measurements = run(arguments.rows)
    if arguments.json:
        print(json.dumps([asdict(item) for item in measurements], indent=2))
    else:
        print("format       scenario             rows       sec      rows/s   peak MiB  disk MiB")
        for item in measurements:
            print(
                f"{item.format:<12} {item.scenario:<20} {item.rows:>8,} "
                f"{item.seconds:>9.3f} {item.rows_per_second:>11,.0f} "
                f"{item.peak_memory_mib:>10.2f} {item.storage_mib:>9.2f}"
            )
