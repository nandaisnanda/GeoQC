"""Bounded upload decoding, filename validation, and dataset verification."""

import base64
import binascii
from dataclasses import dataclass
from pathlib import Path

import pyogrio  # type: ignore[import-untyped]
from fastapi import HTTPException

from geoqc.interfaces.api.request_models import UploadedFile
from geoqc.interfaces.api.settings import (
    ALLOWED_SHAPEFILE_SUFFIXES as _ALLOWED_SHAPEFILE_SUFFIXES,
)
from geoqc.interfaces.api.settings import (
    MAX_DECODED_UPLOAD_BYTES as _MAX_DECODED_UPLOAD_BYTES,
)
from geoqc.interfaces.api.settings import (
    MAX_FEATURES as _MAX_FEATURES,
)
from geoqc.interfaces.api.settings import (
    REQUIRED_SHAPEFILE_SUFFIXES as _REQUIRED_SHAPEFILE_SUFFIXES,
)
from geoqc.interfaces.api.settings import (
    SINGLE_FILE_DRIVERS as _SINGLE_FILE_DRIVERS,
)
from geoqc.interfaces.api.settings import (
    WINDOWS_RESERVED_NAMES as _WINDOWS_RESERVED_NAMES,
)


@dataclass(frozen=True, slots=True)
class _DatasetSelection:
    """Validated dataset entry point and optional layer."""

    filename: str
    layer: str | None = None


def _decode_components(
    files: list[UploadedFile],
    *,
    max_upload_bytes: int = _MAX_DECODED_UPLOAD_BYTES,
) -> dict[str, bytes]:
    """Decode a bounded set of safe, uniquely named upload components."""
    components: dict[str, bytes] = {}
    max_encoded_chars = ((max_upload_bytes + 2) // 3) * 4
    if sum(len(upload.content_base64) for upload in files) > max_encoded_chars:
        raise HTTPException(
            status_code=413, detail="The total upload exceeds the configured limit."
        )

    total_size = 0
    for uploaded_file in files:
        name = uploaded_file.name
        _validate_filename(name)
        normalized_name = name.casefold()
        if normalized_name in components:
            raise HTTPException(status_code=400, detail=f"Duplicate component: {name}")
        try:
            content = base64.b64decode(uploaded_file.content_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid base64 content: {name}",
            ) from error
        total_size += len(content)
        if total_size > max_upload_bytes:
            raise HTTPException(
                status_code=413, detail="The total upload exceeds the configured limit."
            )
        components[normalized_name] = content
    return components


def _validate_filename(name: str) -> None:
    """Reject traversal, Windows device names, ADS paths, and ambiguous names."""
    path = Path(name)
    if (
        path.name != name
        or name in {".", ".."}
        or ":" in name
        or name.endswith((" ", "."))
        or path.stem.casefold() in _WINDOWS_RESERVED_NAMES
    ):
        raise HTTPException(status_code=400, detail=f"Unsafe filename: {name}")


def _validate_component_set(
    components: dict[str, bytes], requested_layer: str | None
) -> _DatasetSelection:
    """Select exactly one supported dataset and reject mixed components."""
    names = tuple(components)
    suffixes = {Path(name).suffix for name in names}
    if ".shp" in suffixes or len(names) > 1:
        unsupported = suffixes - _ALLOWED_SHAPEFILE_SUFFIXES
        if unsupported:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported extension: {', '.join(sorted(unsupported))}",
            )
        missing = _REQUIRED_SHAPEFILE_SUFFIXES - suffixes
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required component: {', '.join(sorted(missing))}",
            )
        if len({Path(name).stem for name in names}) != 1:
            raise HTTPException(
                status_code=400,
                detail="All Shapefile components must have the same base name.",
            )
        if requested_layer is not None:
            raise HTTPException(
                status_code=400,
                detail="The layer parameter is not valid for a Shapefile.",
            )
        return _DatasetSelection(next(name for name in names if Path(name).suffix == ".shp"))

    suffix = next(iter(suffixes))
    if suffix not in _SINGLE_FILE_DRIVERS:
        shown_suffix = suffix or "(no extension)"
        raise HTTPException(status_code=400, detail=f"Unsupported extension: {shown_suffix}")
    return _DatasetSelection(names[0], requested_layer)


def _resolve_layer(dataset_path: Path, requested_layer: str | None) -> str | None:
    """Resolve a layer without silently choosing from an ambiguous container."""
    if dataset_path.suffix != ".gpkg":
        if requested_layer is not None:
            raise HTTPException(
                status_code=400,
                detail="The layer parameter is supported only for GeoPackage.",
            )
        return None

    available_layers = [str(row[0]) for row in pyogrio.list_layers(dataset_path)]
    if requested_layer is not None:
        if requested_layer not in available_layers:
            raise HTTPException(status_code=400, detail="The GeoPackage layer was not found.")
        return requested_layer
    if len(available_layers) != 1:
        raise HTTPException(
            status_code=400,
            detail="The GeoPackage has multiple layers; specify the layer parameter.",
        )
    return available_layers[0]


def _verify_dataset(
    dataset_path: Path, layer: str | None, *, max_features: int = _MAX_FEATURES
) -> None:
    """Verify the detected GDAL driver and reject oversized datasets before loading."""
    info = pyogrio.read_info(dataset_path, layer=layer)
    detected_driver = str(info.get("driver", ""))
    suffix = dataset_path.suffix
    expected = frozenset({"ESRI Shapefile"}) if suffix == ".shp" else _SINGLE_FILE_DRIVERS[suffix]
    if detected_driver not in expected:
        raise HTTPException(
            status_code=422,
            detail="The file content does not match the dataset extension.",
        )
    feature_count = info.get("features")
    if isinstance(feature_count, int) and feature_count > max_features:
        raise HTTPException(
            status_code=413,
            detail=f"The dataset exceeds the {max_features:,}-feature limit.",
        )
    geometry_type = info.get("geometry_type")
    if geometry_type is None or str(geometry_type).casefold() == "none":
        raise HTTPException(status_code=422, detail="The dataset has no geometry column.")
