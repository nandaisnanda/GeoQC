"""Geometry validation and repair HTTP routes."""

import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter, HTTPException
from pyogrio.errors import DataSourceError  # type: ignore[import-untyped]
from shapely.errors import GEOSException

from geoqc import repair_geometries
from geoqc.application.streaming.geometry import GeometryAuditResult
from geoqc.application.streaming.models import DatasetSource
from geoqc.domain.exceptions import GeoQCError
from geoqc.infrastructure.gis.automatic_geometry_engine import AutomaticGeometryEngine
from geoqc.infrastructure.gis.streaming import default_reader_registry
from geoqc.interfaces.api.dataset_io import _frame_geojson, _frame_geometries, _read_frame
from geoqc.interfaces.api.request_models import (
    GeometryFindingResponse,
    GeometryIssueResponse,
    GeospatialRepairRequest,
    GeospatialRepairResponse,
    GeospatialValidationRequest,
    GeospatialValidationResponse,
    RepairActionResponse,
    RepairFeatureResponse,
)
from geoqc.interfaces.api.settings import MAX_FEATURES as _MAX_FEATURES
from geoqc.interfaces.api.settings import MAX_REPORTED_FEATURES as _MAX_REPORTED_FEATURES
from geoqc.interfaces.api.settings import STREAMING_CHUNK_SIZE as _STREAMING_CHUNK_SIZE
from geoqc.interfaces.api.upload_security import (
    _decode_components,
    _resolve_layer,
    _validate_component_set,
    _verify_dataset,
)

LOGGER = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/geometry/validate", response_model=GeospatialValidationResponse)
@router.post(
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
        except (
            OSError,
            ValueError,
            RuntimeError,
            DataSourceError,
            GEOSException,
            GeoQCError,
        ) as error:
            LOGGER.warning("Geospatial upload could not be read")
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


@router.post("/api/geometry/repair", response_model=GeospatialRepairResponse)
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
        except (
            OSError,
            ValueError,
            RuntimeError,
            DataSourceError,
            GEOSException,
            GeoQCError,
        ) as error:
            LOGGER.warning("Geospatial dataset could not be repaired")
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
