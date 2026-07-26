"""Streaming audit orchestration."""

from geoqc.application.ports.streaming import ChunkProcessor, ChunkReader, ResultCollector
from geoqc.application.streaming.iterator import ChunkIterator
from geoqc.application.streaming.models import DatasetSource, StreamingConfig, StreamingResult
from geoqc.domain.exceptions import EmptyLayerError, MissingCRSError


class StreamingEngine:
    """Coordinate metadata, iteration, processing, and result collection."""

    def __init__(
        self,
        reader: ChunkReader,
        processor: ChunkProcessor,
        collector: ResultCollector,
        config: StreamingConfig | None = None,
        *,
        require_crs: bool = False,
    ) -> None:
        self._reader = reader
        self._processor = processor
        self._collector = collector
        self._config = config or StreamingConfig()
        self._require_crs = require_crs

    def run(self, source: DatasetSource) -> StreamingResult:
        metadata = self._reader.inspect(source)
        if self._require_crs and metadata.crs is None:
            raise MissingCRSError(str(source.path), metadata.layer)
        if metadata.feature_count == 0:
            raise EmptyLayerError(str(source.path), metadata.layer)

        feature_count = 0
        chunk_count = 0
        for chunk in ChunkIterator(self._reader, source, self._config):
            self._collector.add(self._processor.process(chunk, metadata))
            feature_count += chunk.size
            chunk_count += 1
        if chunk_count == 0:
            raise EmptyLayerError(str(source.path), metadata.layer)
        return StreamingResult(
            result=self._collector.finish(),
            metadata=metadata,
            feature_count=feature_count,
            chunk_count=chunk_count,
        )
