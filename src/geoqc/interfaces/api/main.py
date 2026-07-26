"""FastAPI composition root and secure local GeoQC endpoints."""

import base64
import binascii
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import geopandas as gpd  # type: ignore[import-untyped]
import pyogrio  # type: ignore[import-untyped]
import shapely
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import GeometryCollection
from shapely.geometry.base import BaseGeometry

from geoqc import (
    ConflictPolicy,
    DatasetSnapshot,
    PriorityWeights,
    RepairCandidate,
    RepairConfig,
    SpatialDuplicateConfig,
    SpatialLayer,
    __version__,
    analyze_spatial_conflicts,
    compare_datasets,
    detect_spatial_duplicates,
    prioritize_repairs,
    repair_geometries,
)
from geoqc.application.streaming.geometry import GeometryAuditResult
from geoqc.application.streaming.models import DatasetSource
from geoqc.infrastructure.gis.automatic_geometry_engine import AutomaticGeometryEngine
from geoqc.infrastructure.gis.streaming import default_reader_registry

LOGGER = logging.getLogger(__name__)

_ENVIRONMENT = os.environ.get("GEOQC_ENVIRONMENT", "development").strip().casefold()
_IS_PRODUCTION = _ENVIRONMENT == "production"

logging.basicConfig(level=os.environ.get("GEOQC_LOG_LEVEL", "INFO").strip().upper())
_REQUIRED_SHAPEFILE_SUFFIXES = frozenset({".shp", ".shx", ".dbf"})
_ALLOWED_SHAPEFILE_SUFFIXES = _REQUIRED_SHAPEFILE_SUFFIXES | {".prj", ".cpg"}
_SINGLE_FILE_DRIVERS: dict[str, frozenset[str]] = {
    ".geojson": frozenset({"GeoJSON"}),
    ".json": frozenset({"GeoJSON"}),
    ".gpkg": frozenset({"GPKG"}),
    ".fgb": frozenset({"FlatGeobuf"}),
    ".parquet": frozenset({"GeoParquet"}),
}
_WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)
_MAX_DECODED_UPLOAD_BYTES = 100 * 1024 * 1024
_MAX_ENCODED_UPLOAD_CHARS = ((_MAX_DECODED_UPLOAD_BYTES + 2) // 3) * 4
_MAX_FEATURES = 1_000_000
_MAX_REPORTED_FEATURES = 1_000
_MAX_REPAIR_FEATURES = 50_000
_STREAMING_CHUNK_SIZE = 16_384


class UploadedFile(BaseModel):
    """One browser-selected geospatial dataset component."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1, max_length=_MAX_ENCODED_UPLOAD_CHARS)


class GeospatialValidationRequest(BaseModel):
    """A bounded geospatial dataset sent by the local web client."""

    model_config = ConfigDict(extra="forbid")

    files: list[UploadedFile] = Field(min_length=1, max_length=5)
    layer: str | None = Field(default=None, min_length=1, max_length=255)


class TopologyRepairOptions(BaseModel):
    """Conservative, coordinate-unit-aware controls for topology repair."""

    model_config = ConfigDict(extra="forbid")

    duplicate_vertex_tolerance: float = Field(default=0.0, ge=0)
    sliver_area_threshold: float = Field(default=1e-9, ge=0)
    sliver_thinness_threshold: float = Field(default=1e-3, ge=0)
    gap_area_threshold: float = Field(default=1e-6, ge=0)
    max_shape_shift: float | None = Field(default=None, ge=0)
    max_relative_area_change: float | None = Field(default=None, ge=0)

    def to_domain(self) -> RepairConfig:
        """Translate the validated transport model into a domain policy."""
        return RepairConfig(**self.model_dump())


class GeospatialRepairRequest(GeospatialValidationRequest):
    """A dataset repair preview with explicit safety thresholds."""

    mode: Literal["preview"] = "preview"
    options: TopologyRepairOptions = Field(default_factory=TopologyRepairOptions)


class SpatialDuplicateRequest(BaseModel):
    """Bounded WKT payload for exact and near-duplicate detection."""

    model_config = ConfigDict(extra="forbid")

    geometries_wkt: list[str] = Field(min_length=1, max_length=_MAX_REPAIR_FEATURES)
    similarity_threshold: float = Field(default=0.85, ge=0, le=1)
    search_tolerance: float = Field(default=0.0, ge=0)
    maximum_pairs: int = Field(default=100_000, ge=1, le=1_000_000)


class DatasetSnapshotRequest(BaseModel):
    """Transport representation of one dataset comparison snapshot."""

    model_config = ConfigDict(extra="forbid")

    geometries_wkt: list[str] = Field(max_length=_MAX_REPAIR_FEATURES)
    attributes: list[dict[str, object]] = Field(default_factory=list)
    crs: str | None = Field(default=None, max_length=255)
    schema_: dict[str, str] = Field(default_factory=dict, alias="schema")
    name: str = Field(default="dataset", min_length=1, max_length=255)

    def to_domain(self) -> DatasetSnapshot:
        return DatasetSnapshot(
            tuple(self.geometries_wkt),
            tuple(self.attributes),
            self.crs,
            self.schema_,
            self.name,
        )


class DatasetComparisonRequest(BaseModel):
    """Two snapshots and a deterministic geometry matching threshold."""

    model_config = ConfigDict(extra="forbid")

    left: DatasetSnapshotRequest
    right: DatasetSnapshotRequest
    match_threshold: float = Field(default=0.5, ge=0, le=1)


class SpatialLayerRequest(BaseModel):
    """One semantic layer used by the conflict analyzer."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    role: str = Field(min_length=1, max_length=64)
    geometries_wkt: list[str] = Field(max_length=_MAX_REPAIR_FEATURES)
    agency: str | None = Field(default=None, max_length=255)

    def to_domain(self) -> SpatialLayer:
        return SpatialLayer(self.name, self.role, tuple(self.geometries_wkt), self.agency)


class SpatialConflictRequest(BaseModel):
    """Bounded multi-layer conflict analysis payload."""

    model_config = ConfigDict(extra="forbid")

    layers: list[SpatialLayerRequest] = Field(min_length=2, max_length=25)


class RepairCandidateRequest(BaseModel):
    """One explainable input to the deterministic priority rule engine."""

    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(min_length=1, max_length=255)
    issue_type: str = Field(min_length=1, max_length=100)
    severity: float = Field(ge=0, le=100)
    impact: float = Field(ge=0, le=100)
    area: float = Field(ge=0)
    feature_count: int = Field(ge=0)
    metadata: dict[str, str] = Field(default_factory=dict)

    def to_domain(self) -> RepairCandidate:
        return RepairCandidate(**self.model_dump())


class RepairPriorityRequest(BaseModel):
    """Candidates accepted by the non-AI repair recommendation engine."""

    model_config = ConfigDict(extra="forbid")

    candidates: list[RepairCandidateRequest] = Field(min_length=1, max_length=100_000)


@dataclass(frozen=True, slots=True)
class _DatasetSelection:
    """Validated dataset entry point and optional layer."""

    filename: str
    layer: str | None = None


app: FastAPI = FastAPI(
    title="GeoQC API",
    description="GIS quality-control API.",
    version=__version__,
    docs_url="/docs" if not _IS_PRODUCTION else None,
    redoc_url="/redoc" if not _IS_PRODUCTION else None,
    openapi_url="/openapi.json" if not _IS_PRODUCTION else None,
)


@app.post("/api/spatial/duplicates")
def spatial_duplicates(payload: SpatialDuplicateRequest) -> dict[str, object]:
    """Return indexed IoU, Hausdorff, and shape-similarity duplicate findings."""
    try:
        geometries = [shapely.from_wkt(value) for value in payload.geometries_wkt]
        report = detect_spatial_duplicates(
            geometries,
            SpatialDuplicateConfig(
                similarity_threshold=payload.similarity_threshold,
                search_tolerance=payload.search_tolerance,
                maximum_pairs=payload.maximum_pairs,
            ),
        )
        return asdict(report)
    except (TypeError, ValueError, shapely.errors.GEOSException) as error:
        raise HTTPException(
            status_code=422, detail="Invalid duplicate-analysis payload."
        ) from error


@app.post("/api/spatial/compare")
def spatial_compare(payload: DatasetComparisonRequest) -> dict[str, object]:
    """Return geometry, attribute, CRS, schema, and boundary differences."""
    try:
        return asdict(
            compare_datasets(
                payload.left.to_domain(),
                payload.right.to_domain(),
                match_threshold=payload.match_threshold,
            )
        )
    except (TypeError, ValueError, shapely.errors.GEOSException) as error:
        raise HTTPException(
            status_code=422, detail="Invalid dataset-comparison payload."
        ) from error


@app.post("/api/spatial/conflicts")
def spatial_conflicts(payload: SpatialConflictRequest) -> dict[str, object]:
    """Return semantic cross-layer conflicts and severity scores."""
    try:
        report = analyze_spatial_conflicts(
            [item.to_domain() for item in payload.layers], ConflictPolicy()
        )
        return asdict(report)
    except (TypeError, ValueError, shapely.errors.GEOSException) as error:
        raise HTTPException(status_code=422, detail="Invalid conflict-analysis payload.") from error


@app.post("/api/repairs/prioritize")
def repair_priorities(payload: RepairPriorityRequest) -> dict[str, object]:
    """Rank repair work using rules only; no AI or LLM is invoked."""
    recommendations = prioritize_repairs(
        [item.to_domain() for item in payload.candidates], PriorityWeights()
    )
    return {"recommendations": [asdict(item) for item in recommendations]}


@app.middleware("http")
async def add_security_headers(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Add browser-safe defaults to every API response."""
    response = await call_next(request)
    if request.url.path in {"/docs", "/redoc"}:
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; img-src data: https://fastapi.tiangolo.com; "
            "script-src https://cdn.jsdelivr.net; "
            "style-src 'unsafe-inline' https://cdn.jsdelivr.net; "
            "frame-ancestors 'none'"
        )
    else:
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


class GeometryIssueResponse(BaseModel):
    """One normalized geometry issue returned by the API."""

    model_config = ConfigDict(extra="forbid")

    type: str
    message: str


class GeometryFindingResponse(BaseModel):
    """Issues associated with one zero-based feature index."""

    model_config = ConfigDict(extra="forbid")

    feature_index: int = Field(ge=0)
    issues: list[GeometryIssueResponse]


class GeospatialValidationResponse(BaseModel):
    """Validated and documented response contract for dataset validation."""

    model_config = ConfigDict(extra="forbid")

    filename: str
    layer: str | None
    feature_count: int = Field(ge=0)
    valid_feature_count: int = Field(ge=0)
    invalid_feature_count: int = Field(ge=0)
    issue_counts: dict[str, int]
    findings: list[GeometryFindingResponse]
    findings_truncated: bool


@app.post("/api/geometry/validate", response_model=GeospatialValidationResponse)
@app.post(
    "/api/geometry/validate-shapefile",
    response_model=GeospatialValidationResponse,
    include_in_schema=False,
)
def validate_geospatial(payload: GeospatialValidationRequest) -> GeospatialValidationResponse:
    """Validate every geometry in one bounded, allowlisted geospatial dataset."""
    components = _decode_components(payload.files)
    selection = _validate_component_set(components, payload.layer)
    with TemporaryDirectory(prefix="geoqc-") as temporary_directory:
        directory = Path(temporary_directory)
        for name, content in components.items():
            (directory / name).write_bytes(content)
        dataset_path = directory / selection.filename
        try:
            layer = _resolve_layer(dataset_path, selection.layer)
            _verify_dataset(dataset_path, layer)
            source = DatasetSource(dataset_path, layer=layer)
            reader = default_reader_registry().resolve(source)
            metadata = reader.inspect(source)
            if metadata.feature_count is not None and metadata.feature_count > _MAX_FEATURES:
                raise HTTPException(
                    status_code=413,
                    detail=f"The dataset exceeds the {_MAX_FEATURES:,}-feature limit.",
                )
            audit, _decision = AutomaticGeometryEngine(
                reader,
                maximum_findings=_MAX_REPORTED_FEATURES,
                chunk_size=_STREAMING_CHUNK_SIZE,
            ).run(source)
            if not isinstance(audit, GeometryAuditResult):
                raise TypeError("Unexpected geometry audit result")
            if audit.feature_count > _MAX_FEATURES:
                raise HTTPException(
                    status_code=413,
                    detail=f"The dataset exceeds the {_MAX_FEATURES:,}-feature limit.",
                )
        except HTTPException:
            raise
        except Exception as error:
            LOGGER.warning("Geospatial upload could not be read", exc_info=error)
            raise HTTPException(
                status_code=422,
                detail="The geospatial dataset could not be read or has an invalid format.",
            ) from error

    return GeospatialValidationResponse(
        filename=selection.filename,
        layer=layer,
        feature_count=audit.feature_count,
        valid_feature_count=audit.feature_count - audit.invalid_feature_count,
        invalid_feature_count=audit.invalid_feature_count,
        issue_counts=audit.issue_counts,
        findings=[
            GeometryFindingResponse(
                feature_index=finding.feature_index,
                issues=[
                    GeometryIssueResponse(type=item[0], message=item[1]) for item in finding.issues
                ],
            )
            for finding in audit.findings
        ],
        findings_truncated=audit.invalid_feature_count > len(audit.findings),
    )


class RepairActionResponse(BaseModel):
    """One repair step applied to a geometry."""

    model_config = ConfigDict(extra="forbid")

    issue_type: str
    strategy: str
    detail: str


class RepairFeatureResponse(BaseModel):
    """A single changed feature with its before/after geometry as WKT."""

    model_config = ConfigDict(extra="forbid")

    feature_index: int = Field(ge=0)
    status: str
    geometry_type: str
    actions: list[RepairActionResponse]
    area_before: float
    area_after: float
    shape_shift: float
    before_wkt: str
    after_wkt: str


class GeospatialRepairResponse(BaseModel):
    """Aggregate repair report plus a downloadable repaired dataset."""

    model_config = ConfigDict(extra="forbid")

    filename: str
    layer: str | None
    mode: Literal["preview"]
    total: int = Field(ge=0)
    repaired: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    failed: int = Field(ge=0)
    action_counts: dict[str, int]
    total_area_delta: float
    max_shape_shift: float
    findings: list[RepairFeatureResponse]
    findings_truncated: bool
    original_geojson: str
    repaired_geojson: str


@app.post("/api/geometry/repair", response_model=GeospatialRepairResponse)
def repair_geospatial(payload: GeospatialRepairRequest) -> GeospatialRepairResponse:
    """Preview a safe repair for every geometry in one bounded coverage."""
    components = _decode_components(payload.files)
    selection = _validate_component_set(components, payload.layer)
    with TemporaryDirectory(prefix="geoqc-") as temporary_directory:
        directory = Path(temporary_directory)
        for name, content in components.items():
            (directory / name).write_bytes(content)
        dataset_path = directory / selection.filename
        try:
            layer = _resolve_layer(dataset_path, selection.layer)
            _verify_dataset(dataset_path, layer)
            frame = _read_frame(dataset_path, layer)
            geometries = _frame_geometries(frame)
            coverage = repair_geometries(geometries, payload.options.to_domain())
        except HTTPException:
            raise
        except Exception as error:
            LOGGER.warning("Geospatial dataset could not be repaired", exc_info=error)
            raise HTTPException(
                status_code=422,
                detail="The geospatial dataset could not be read or has an invalid format.",
            ) from error

    report = coverage.report
    findings: list[RepairFeatureResponse] = []
    for item in report.results:
        if not item.result.is_changed:
            continue
        if len(findings) >= _MAX_REPORTED_FEATURES:
            break
        findings.append(
            RepairFeatureResponse(
                feature_index=item.feature_index,
                status=str(item.result.status.value),
                geometry_type=item.result.geometry_type,
                actions=[
                    RepairActionResponse(
                        issue_type=str(action.issue_type.value),
                        strategy=action.strategy,
                        detail=action.detail,
                    )
                    for action in item.result.actions
                ],
                area_before=item.result.metrics.area_before,
                area_after=item.result.metrics.area_after,
                shape_shift=item.result.metrics.shape_shift,
                before_wkt=item.result.before_wkt,
                after_wkt=item.result.after_wkt,
            )
        )

    return GeospatialRepairResponse(
        filename=selection.filename,
        layer=layer,
        mode=payload.mode,
        total=report.total,
        repaired=report.repaired_count,
        unchanged=report.unchanged_count,
        failed=report.failed_count,
        action_counts=report.action_counts,
        total_area_delta=report.total_area_delta,
        max_shape_shift=report.max_shape_shift,
        findings=findings,
        findings_truncated=report.repaired_count > len(findings),
        original_geojson=_frame_geojson(frame, coverage.before_wkt),
        repaired_geojson=_frame_geojson(frame, coverage.after_wkt),
    )


def _read_frame(dataset_path: Path, layer: str | None) -> gpd.GeoDataFrame:
    """Read a bounded dataset while retaining attributes, index, and CRS."""
    frame = pyogrio.read_dataframe(dataset_path, layer=layer)
    if len(frame) > _MAX_REPAIR_FEATURES:
        raise HTTPException(
            status_code=413,
            detail=f"Repair is limited to {_MAX_REPAIR_FEATURES:,} features per dataset.",
        )
    return frame


def _frame_geometries(frame: gpd.GeoDataFrame) -> list[BaseGeometry]:
    """Return Shapely geometries, representing missing values as empty geometry."""
    empty = GeometryCollection()
    return [geometry if geometry is not None else empty for geometry in frame.geometry]


def _frame_geojson(frame: gpd.GeoDataFrame, wkts: tuple[str, ...]) -> str:
    """Serialize a geometry snapshot without discarding source attributes or CRS."""
    if len(frame) != len(wkts):
        raise ValueError("geometry snapshot length does not match the source frame")
    snapshot = frame.copy()
    snapshot.geometry = [shapely.from_wkt(wkt) for wkt in wkts]
    if snapshot.crs is not None:
        snapshot = snapshot.to_crs("EPSG:4326")
    geometry_name = snapshot.geometry.name
    features: list[dict[str, object]] = []
    for feature_id, (_, row) in enumerate(snapshot.iterrows()):
        properties = {
            str(name): _json_value(value) for name, value in row.items() if name != geometry_name
        }
        geometry = row[geometry_name]
        features.append(
            {
                "type": "Feature",
                "id": str(feature_id),
                "properties": properties,
                "geometry": shapely.geometry.mapping(geometry),
            }
        )
    return json.dumps({"type": "FeatureCollection", "features": features})


def _json_value(value: object) -> object:
    """Convert scalar dataframe values into strict JSON-compatible values."""
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _decode_components(files: list[UploadedFile]) -> dict[str, bytes]:
    """Decode a bounded set of safe, uniquely named upload components."""
    components: dict[str, bytes] = {}
    if sum(len(upload.content_base64) for upload in files) > _MAX_ENCODED_UPLOAD_CHARS:
        raise HTTPException(status_code=413, detail="The total upload exceeds 100 MiB.")

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
        if total_size > _MAX_DECODED_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="The total upload exceeds 100 MiB.")
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


def _verify_dataset(dataset_path: Path, layer: str | None) -> None:
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
    if isinstance(feature_count, int) and feature_count > _MAX_FEATURES:
        raise HTTPException(
            status_code=413,
            detail=f"The dataset exceeds the {_MAX_FEATURES:,}-feature limit.",
        )
    geometry_type = info.get("geometry_type")
    if geometry_type is None or str(geometry_type).casefold() == "none":
        raise HTTPException(status_code=422, detail="The dataset has no geometry column.")
