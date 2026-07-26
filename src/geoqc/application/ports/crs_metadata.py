"""Inbound-facing port for reading CRS metadata from GIS datasets."""

from typing import Protocol

from geoqc.domain.models import DatasetCrsMetadata, DatasetSource


class CrsMetadataReader(Protocol):
    """Read normalized CRS metadata without exposing a GIS framework."""

    def read(self, source: DatasetSource) -> DatasetCrsMetadata:
        """Read metadata only; implementations must not load feature rows."""
        ...
