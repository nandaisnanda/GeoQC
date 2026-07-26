"""Native GDAL Arrow streaming for OGR vector formats."""

from collections.abc import Iterator
from typing import Any

import pyogrio  # type: ignore[import-untyped]

from geoqc.application.streaming.models import DatasetMetadata, DatasetSource, FeatureChunk
from geoqc.domain.exceptions import CorruptDatasetError, DatasetEncodingError


class PyogrioChunkReader:
    """Read GeoPackage, Shapefile, and GeoJSON through GDAL Arrow batches."""

    _SUFFIXES = frozenset({".gpkg", ".shp", ".geojson", ".json", ".fgb"})

    def supports(self, source: DatasetSource) -> bool:
        return source.path.suffix.casefold() in self._SUFFIXES

    def inspect(self, source: DatasetSource) -> DatasetMetadata:
        try:
            info: dict[str, Any] = pyogrio.read_info(source.path, layer=source.layer)
        except UnicodeError as error:
            raise DatasetEncodingError(f"Cannot decode attributes in {source.path!s}") from error
        except Exception as error:
            raise CorruptDatasetError(f"Cannot inspect dataset {source.path!s}") from error
        geometry_type = info.get("geometry_type")
        if geometry_type is None or str(geometry_type).casefold() == "none":
            raise CorruptDatasetError(f"Dataset {source.path!s} has no geometry column")
        count = info.get("features")
        return DatasetMetadata(
            driver=str(info.get("driver", "")),
            layer=source.layer or str(info.get("layer_name") or "") or None,
            crs=str(info["crs"]) if info.get("crs") else None,
            feature_count=count if isinstance(count, int) and count >= 0 else None,
            geometry_column="wkb_geometry",
            encoding=source.encoding or (str(info["encoding"]) if info.get("encoding") else None),
        )

    def iter_chunks(self, source: DatasetSource, chunk_size: int) -> Iterator[FeatureChunk]:
        offset = 0
        try:
            with pyogrio.open_arrow(
                source.path,
                layer=source.layer,
                encoding=source.encoding,
                read_geometry=True,
                batch_size=chunk_size,
                use_pyarrow=True,
            ) as (metadata, batches):
                geometry_name = str(metadata.get("geometry_name") or "wkb_geometry")
                for batch in batches:
                    size = len(batch)
                    if size:
                        # Keep the actual backend geometry field discoverable by processors.
                        yield FeatureChunk(
                            offset=offset,
                            features=(geometry_name, batch),
                            size=size,
                        )
                        offset += size
        except UnicodeError as error:
            raise DatasetEncodingError(f"Cannot decode attributes in {source.path!s}") from error
        except (MemoryError, DatasetEncodingError):
            raise
        except Exception as error:
            raise CorruptDatasetError(f"Cannot stream dataset {source.path!s}") from error
