"""Bounded dataset profiling for automatic engine selection."""

import os
from pathlib import Path
from typing import Any, cast

import shapely

from geoqc.application.engine_selection import DatasetProfile, GeometryComplexity
from geoqc.application.ports.streaming import ChunkReader
from geoqc.application.streaming.models import DatasetMetadata, DatasetSource

_SAMPLE_FEATURES = 256
_FORMAT_EXPANSION: dict[str, float] = {
    "GeoJSON": 2.5,
    "GeoParquet": 6.0,
    "GPKG": 4.0,
    "ESRI Shapefile": 3.0,
}
_MINIMUM_BYTES_PER_FEATURE = 512


class DatasetProfiler:
    """Build a conservative profile using metadata and at most one small batch."""

    def profile(
        self,
        source: DatasetSource,
        reader: ChunkReader,
        metadata: DatasetMetadata | None = None,
    ) -> DatasetProfile:
        inspected = metadata or reader.inspect(source)
        size_bytes = _dataset_size(source.path)
        geometry, sampled_bytes = _sample_geometry(source, reader, inspected.geometry_column)
        estimated = _estimated_memory(
            size_bytes,
            inspected.driver,
            inspected.feature_count,
            geometry.sampled_features,
            sampled_bytes,
        )
        return DatasetProfile(
            driver=inspected.driver,
            size_bytes=size_bytes,
            feature_count=inspected.feature_count,
            estimated_memory_bytes=estimated,
            available_memory_bytes=_available_memory(),
            geometry=geometry,
        )


def _dataset_size(path: Path) -> int:
    if path.suffix.casefold() != ".shp":
        return path.stat().st_size
    return sum(
        candidate.stat().st_size
        for candidate in path.parent.iterdir()
        if candidate.is_file() and candidate.stem.casefold() == path.stem.casefold()
    )


def _sample_geometry(
    source: DatasetSource,
    reader: ChunkReader,
    geometry_column: str,
) -> tuple[GeometryComplexity, int]:
    chunks = reader.iter_chunks(source, _SAMPLE_FEATURES)
    first = next(chunks, None)
    if first is None:
        return GeometryComplexity(), 0
    features = first.features
    if isinstance(features, tuple):
        column_name, batch = features
    else:
        column_name, batch = geometry_column, features
    column = batch.column(column_name)
    values = column.to_pylist()
    sampled_bytes = sum(len(value) for value in values if isinstance(value, bytes))
    geometries = shapely.from_wkb(values, on_invalid="ignore")
    vertices = [
        int(shapely.get_num_coordinates(item)) if item is not None else 0 for item in geometries
    ]
    if not vertices:
        return GeometryComplexity(), sampled_bytes
    return (
        GeometryComplexity(
            sampled_features=len(vertices),
            average_vertices=sum(vertices) / len(vertices),
            maximum_vertices=max(vertices),
        ),
        sampled_bytes,
    )


def _estimated_memory(
    size_bytes: int,
    driver: str,
    feature_count: int | None,
    sampled_features: int,
    sampled_bytes: int,
) -> int:
    expansion = _FORMAT_EXPANSION.get(driver, 4.0)
    disk_estimate = int(size_bytes * expansion)
    if feature_count is None:
        return disk_estimate
    sampled_per_feature = sampled_bytes // sampled_features if sampled_features else 0
    per_feature = max(_MINIMUM_BYTES_PER_FEATURE, sampled_per_feature * 3)
    return max(disk_estimate, feature_count * per_feature)


def _available_memory() -> int | None:
    try:
        if os.name == "nt":
            import ctypes

            class _MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("memory_load", ctypes.c_ulong),
                    ("total_physical", ctypes.c_ulonglong),
                    ("available_physical", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong),
                    ("available_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended_virtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatus()
            status.length = ctypes.sizeof(status)
            ctypes_api = cast(Any, ctypes)
            if ctypes_api.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.available_physical)
        os_api = cast(Any, os)
        pages = os_api.sysconf("SC_AVPHYS_PAGES")
        page_size = os_api.sysconf("SC_PAGE_SIZE")
        return int(pages * page_size)
    except (AttributeError, OSError, ValueError):
        return None
