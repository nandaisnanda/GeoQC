"""Extensible selection of readers by source format."""

from geoqc.application.ports.streaming import ChunkReader
from geoqc.application.streaming.models import DatasetSource
from geoqc.domain.exceptions import UnsupportedDatasetFormatError


class ReaderRegistry:
    """Select the first registered reader supporting a source."""

    def __init__(self, readers: tuple[ChunkReader, ...] = ()) -> None:
        self._readers = list(readers)

    def register(self, reader: ChunkReader) -> None:
        self._readers.append(reader)

    def resolve(self, source: DatasetSource) -> ChunkReader:
        for reader in self._readers:
            if reader.supports(source):
                return reader
        raise UnsupportedDatasetFormatError(
            f"No streaming reader supports {source.path.suffix or source.path.name!r}"
        )
