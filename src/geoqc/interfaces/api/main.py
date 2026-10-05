"""Compatibility exports for the canonical modular FastAPI application."""

from geoqc.interfaces.api.app import add_security_headers as add_security_headers
from geoqc.interfaces.api.app import app as app
from geoqc.interfaces.api.app import create_app as create_app
from geoqc.interfaces.api.geometry_routes import repair_geospatial as repair_geospatial
from geoqc.interfaces.api.geometry_routes import validate_geospatial as validate_geospatial
from geoqc.interfaces.api.request_models import DatasetComparisonRequest as DatasetComparisonRequest
from geoqc.interfaces.api.request_models import DatasetSnapshotRequest as DatasetSnapshotRequest
from geoqc.interfaces.api.request_models import GeometryFindingResponse as GeometryFindingResponse
from geoqc.interfaces.api.request_models import GeometryIssueResponse as GeometryIssueResponse
from geoqc.interfaces.api.request_models import GeospatialRepairRequest as GeospatialRepairRequest
from geoqc.interfaces.api.request_models import GeospatialRepairResponse as GeospatialRepairResponse
from geoqc.interfaces.api.request_models import (
    GeospatialValidationRequest as GeospatialValidationRequest,
)
from geoqc.interfaces.api.request_models import (
    GeospatialValidationResponse as GeospatialValidationResponse,
)
from geoqc.interfaces.api.request_models import RepairActionResponse as RepairActionResponse
from geoqc.interfaces.api.request_models import RepairCandidateRequest as RepairCandidateRequest
from geoqc.interfaces.api.request_models import RepairFeatureResponse as RepairFeatureResponse
from geoqc.interfaces.api.request_models import RepairPriorityRequest as RepairPriorityRequest
from geoqc.interfaces.api.request_models import SpatialConflictRequest as SpatialConflictRequest
from geoqc.interfaces.api.request_models import SpatialDuplicateRequest as SpatialDuplicateRequest
from geoqc.interfaces.api.request_models import SpatialLayerRequest as SpatialLayerRequest
from geoqc.interfaces.api.request_models import TopologyRepairOptions as TopologyRepairOptions
from geoqc.interfaces.api.request_models import UploadedFile as UploadedFile
from geoqc.interfaces.api.spatial_routes import repair_priorities as repair_priorities
from geoqc.interfaces.api.spatial_routes import spatial_compare as spatial_compare
from geoqc.interfaces.api.spatial_routes import spatial_conflicts as spatial_conflicts
from geoqc.interfaces.api.spatial_routes import spatial_duplicates as spatial_duplicates
