"""Manual 1/2/4/8-worker benchmark for independent GeoPackage audits."""

import argparse
import json
import tempfile
import time
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

from geoqc.application.parallel import ParallelBatchExecutor
from geoqc.infrastructure.gis.parallel_audit import audit_dataset


def build_inputs(folder: Path, files: int, features: int) -> tuple[Path, ...]:
    sources = []
    geometry = [Point(index, index) for index in range(features)]
    for index in range(files):
        source = folder / f"benchmark-{index:03d}.gpkg"
        gpd.GeoDataFrame({"id": range(features)}, geometry=geometry, crs="EPSG:4326").to_file(
            source, driver="GPKG"
        )
        sources.append(source)
    return tuple(sources)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=8)
    parser.add_argument("--features", type=int, default=100_000)
    arguments = parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary:
        sources = build_inputs(Path(temporary), arguments.files, arguments.features)
        measurements = {}
        for workers in (1, 2, 4, 8):
            started = time.perf_counter()
            result = ParallelBatchExecutor().run(
                sources,
                audit_dataset,
                requested_workers=workers,
                multiprocessing_safe=workers > 1,
            )
            measurements[str(workers)] = {
                "seconds": time.perf_counter() - started,
                "datasets": result.total,
                "features": arguments.files * arguments.features,
            }
        print(json.dumps(measurements, indent=2))


if __name__ == "__main__":
    main()
