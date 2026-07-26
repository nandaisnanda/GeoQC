"""Pyogrio adapter for efficient metadata-only CRS inspection."""

from typing import Any, cast

import pyogrio  # type: ignore[import-untyped]
from pyproj import CRS
from pyproj.exceptions import CRSError

from geoqc.domain.exceptions import DatasetMetadataReadError
from geoqc.domain.models import CrsMetadata, DatasetCrsMetadata, DatasetSource


class PyogrioCrsMetadataReader:
    """Read and normalize CRS metadata without loading dataset features."""

    def read(self, source: DatasetSource) -> DatasetCrsMetadata:
        """Read one dataset's metadata and canonicalize its CRS with pyproj."""
        try:
            info = cast(
                dict[str, Any],
                pyogrio.read_info(source.uri, layer=source.layer),
            )
        except Exception as error:
            raise DatasetMetadataReadError(source.identifier, str(error)) from error

        raw_crs = info.get("crs")
        if raw_crs is None or not str(raw_crs).strip():
            return DatasetCrsMetadata(source=source, crs=None)

        try:
            parsed = CRS.from_user_input(raw_crs)
        except CRSError as error:
            raise DatasetMetadataReadError(
                source.identifier,
                f"Invalid CRS metadata: {error}",
            ) from error

        authority = parsed.to_authority()
        authority_name = f"{authority[0]}:{authority[1]}" if authority else None
        display_name = authority_name or parsed.name
        return DatasetCrsMetadata(
            source=source,
            crs=CrsMetadata(
                canonical_wkt=parsed.to_wkt(version="WKT2_2019", pretty=False),
                display_name=display_name,
                authority=authority_name,
            ),
        )
