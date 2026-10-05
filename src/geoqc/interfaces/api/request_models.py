"""Strict request and response models for the GeoQC API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from geoqc import DatasetSnapshot, RepairCandidate, RepairConfig, SpatialLayer
from geoqc.interfaces.api.settings import MAX_ENCODED_UPLOAD_CHARS as _MAX_ENCODED_UPLOAD_CHARS
from geoqc.interfaces.api.settings import MAX_REPAIR_FEATURES as _MAX_REPAIR_FEATURES


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


class JobCreationResponse(BaseModel):
    """Accepted process-local validation job."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    state: Literal["queued"]
    status_url: str
    request_id: str


class JobStatusResponse(BaseModel):
    """Current state and optional terminal output of one job."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    state: Literal["queued", "running", "succeeded", "failed"]
    request_id: str
    result: dict[str, object] | None = None
    error: str | None = None


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
