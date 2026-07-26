from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
from shapely.geometry import Point

from geoqc.application.parallel import ParallelBatchExecutor
from geoqc.infrastructure.gis.parallel_audit import audit_dataset


def test_parallel_streaming_matches_serial_and_is_read_only(tmp_path: Path) -> None:
    sources = []
    for index in range(3):
        source = tmp_path / f"data-{index}.gpkg"
        gpd.GeoDataFrame(
            {"id": [1, 2]},
            geometry=[Point(index, 0), Point(index, 1)],
            crs="EPSG:4326",
        ).to_file(source, driver="GPKG")
        sources.append(source)
    before = {source: source.read_bytes() for source in sources}
    executor = ParallelBatchExecutor()

    serial = executor.run(sources, audit_dataset, multiprocessing_safe=False)
    parallel = executor.run(sources, audit_dataset, requested_workers=2)

    assert [item.status for item in serial.items] == [item.status for item in parallel.items]
    assert [item.value.result for item in serial.items if item.value is not None] == [
        item.value.result for item in parallel.items if item.value is not None
    ]
    assert [item.value.decision.engine for item in serial.items if item.value is not None] == [
        item.value.decision.engine for item in parallel.items if item.value is not None
    ]
    assert {source: source.read_bytes() for source in sources} == before
