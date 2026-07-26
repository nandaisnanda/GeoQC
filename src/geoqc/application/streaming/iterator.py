"""Reader-neutral iterator lifecycle and error normalization."""

from collections.abc import Iterator

from geoqc.application.ports.streaming import ChunkReader
from geoqc.application.streaming.models import DatasetSource, FeatureChunk, StreamingConfig
from geoqc.domain.exceptions import StreamingMemoryError


class ChunkIterator:
    """Iterate a reader with a configured memory bound."""

    def __init__(self, reader: ChunkReader, source: DatasetSource, config: StreamingConfig) -> None:
        self._reader = reader
        self._source = source
        self._config = config

    def __iter__(self) -> Iterator[FeatureChunk]:
        try:
            yield from self._reader.iter_chunks(self._source, self._config.chunk_size)
        except MemoryError as error:
            raise StreamingMemoryError(str(self._source.path), self._config.chunk_size) from error
