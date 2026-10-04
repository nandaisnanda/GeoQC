"""Limits and allowlists for the GeoQC HTTP boundary."""

import os

ENVIRONMENT = os.environ.get("GEOQC_ENVIRONMENT", "development").strip().casefold()
IS_PRODUCTION = ENVIRONMENT == "production"
REQUIRED_SHAPEFILE_SUFFIXES = frozenset({".shp", ".shx", ".dbf"})
ALLOWED_SHAPEFILE_SUFFIXES = REQUIRED_SHAPEFILE_SUFFIXES | {".prj", ".cpg"}
SINGLE_FILE_DRIVERS: dict[str, frozenset[str]] = {
    ".geojson": frozenset({"GeoJSON"}),
    ".json": frozenset({"GeoJSON"}),
    ".gpkg": frozenset({"GPKG"}),
    ".fgb": frozenset({"FlatGeobuf"}),
    ".parquet": frozenset({"GeoParquet"}),
}
WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)
MAX_DECODED_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_ENCODED_UPLOAD_CHARS = ((MAX_DECODED_UPLOAD_BYTES + 2) // 3) * 4
MAX_FEATURES = 1_000_000
MAX_REPORTED_FEATURES = 1_000
MAX_REPAIR_FEATURES = 50_000
STREAMING_CHUNK_SIZE = 16_384
