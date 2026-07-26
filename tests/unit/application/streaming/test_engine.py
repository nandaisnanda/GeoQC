from collections.abc import Iterator
from pathlib import Path

import pytest

from geoqc.application.streaming.engine import StreamingEngine
from geoqc.application.streaming.iterator import ChunkIterator
from geoqc.application.streaming.models import (
    DatasetMetadata,
    DatasetSource,
    FeatureChunk,
    StreamingConfig,
)
from geoqc.domain.exceptions import EmptyLayerError, MissingCRSError, StreamingMemoryError


class StubReader:
    def __init__(self, chunks: tuple[FeatureChunk, ...], *, count: int | None = None) -> None:
        self.chunks = chunks
        self.metadata = DatasetMetadata("test", None, "EPSG:4326", count, "geometry")
        self.requested_chunk_size: int | None = None

    def supports(self, source: DatasetSource) -> bool:
        return True

    def inspect(self, source: DatasetSource) -> DatasetMetadata:
        return self.metadata

    def iter_chunks(self, source: DatasetSource, chunk_size: int) -> Iterator[FeatureChunk]:
        self.requested_chunk_size = chunk_size
        yield from self.chunks


class Processor:
    def process(self, chunk: FeatureChunk, metadata: DatasetMetadata) -> object:
        return chunk.size


class Collector:
    def __init__(self) -> None:
        self.values: list[int] = []

    def add(self, result: object) -> None:
        assert isinstance(result, int)
        self.values.append(result)

    def finish(self) -> object:
        return sum(self.values)


def test_engine_processes_chunks_in_order_and_returns_statistics() -> None:
    reader = StubReader((FeatureChunk(0, object(), 2), FeatureChunk(2, object(), 1)), count=3)

    result = StreamingEngine(
        reader, Processor(), Collector(), StreamingConfig(chunk_size=2, minimum_chunk_size=1)
    ).run(DatasetSource(Path("roads.geojson")))

    assert result.result == 3
    assert result.feature_count == 3
    assert result.chunk_count == 2
    assert reader.requested_chunk_size == 2


def test_engine_rejects_empty_and_missing_crs_sources() -> None:
    empty = StubReader((), count=0)
    with pytest.raises(EmptyLayerError):
        StreamingEngine(empty, Processor(), Collector()).run(DatasetSource(Path("empty.geojson")))

    unknown = StubReader((), count=None)
    unknown.metadata = DatasetMetadata("test", None, "EPSG:4326", None, "geometry")
    with pytest.raises(EmptyLayerError):
        StreamingEngine(unknown, Processor(), Collector()).run(DatasetSource(Path("empty.geojson")))

    no_crs = StubReader((FeatureChunk(0, object(), 1),), count=1)
    no_crs.metadata = DatasetMetadata("test", None, None, 1, "geometry")
    with pytest.raises(MissingCRSError):
        StreamingEngine(no_crs, Processor(), Collector(), require_crs=True).run(
            DatasetSource(Path("roads.geojson"))
        )


def test_iterator_normalizes_memory_errors() -> None:
    class FailingReader(StubReader):
        def iter_chunks(self, source: DatasetSource, chunk_size: int) -> Iterator[FeatureChunk]:
            raise MemoryError
            yield  # pragma: no cover

    iterator = ChunkIterator(
        FailingReader(()),
        DatasetSource(Path("large.gpkg")),
        StreamingConfig(chunk_size=512, minimum_chunk_size=1),
    )
    with pytest.raises(StreamingMemoryError):
        next(iter(iterator))


@pytest.mark.parametrize(
    ("chunk_size", "minimum"),
    [(0, 1), (10, 0), (10, 11)],
)
def test_streaming_config_rejects_invalid_bounds(chunk_size: int, minimum: int) -> None:
    with pytest.raises(ValueError):
        StreamingConfig(chunk_size=chunk_size, minimum_chunk_size=minimum)
