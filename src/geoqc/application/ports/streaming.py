"""Outbound contracts for bounded geospatial dataset readers."""

from collections.abc import Iterator
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from geoqc.application.streaming.models import DatasetMetadata, DatasetSource, FeatureChunk


class ChunkReader(Protocol):
    """Inspect and read one supported dataset in bounded chunks."""

    def supports(self, source: "DatasetSource") -> bool:
        """Return whether this reader understands the source format."""

    def inspect(self, source: "DatasetSource") -> "DatasetMetadata":
        """Read metadata without materializing all features."""

    def iter_chunks(self, source: "DatasetSource", chunk_size: int) -> Iterator["FeatureChunk"]:
        """Yield bounded feature chunks and release resources when closed."""


class ChunkProcessor(Protocol):
    """Process one chunk without retaining the chunk itself."""

    def process(self, chunk: "FeatureChunk", metadata: "DatasetMetadata") -> object:
        """Return a partial audit result."""


class ResultCollector(Protocol):
    """Combine partial results into one deterministic audit result."""

    def add(self, result: object) -> None:
        """Consume one partial result."""

    def finish(self) -> object:
        """Return the final result."""
