"""HTTP adapter for process-local dataset validation jobs."""

import base64
import shutil
from pathlib import Path
from tempfile import mkdtemp

from fastapi import APIRouter, HTTPException, Request, status

from geoqc.interfaces.api.geometry_routes import validate_payload
from geoqc.interfaces.api.jobs import JobManager, JobQueueFullError
from geoqc.interfaces.api.operations import REQUEST_ID
from geoqc.interfaces.api.request_models import (
    GeospatialValidationRequest,
    JobCreationResponse,
    JobStatusResponse,
    UploadedFile,
)
from geoqc.interfaces.api.settings import ApiSettings
from geoqc.interfaces.api.upload_security import _decode_components, _validate_component_set

router = APIRouter()


@router.post(
    "/api/jobs/geometry/validate",
    response_model=JobCreationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_validation_job(
    payload: GeospatialValidationRequest, request: Request
) -> JobCreationResponse:
    """Queue a validation job while retaining the synchronous endpoint."""
    manager: JobManager = request.app.state.job_manager
    settings: ApiSettings = request.app.state.settings
    components = _decode_components(payload.files, max_upload_bytes=settings.max_upload_bytes)
    _validate_component_set(
        components, payload.layer, allowed_extensions=settings.allowed_extensions
    )
    directory = Path(
        mkdtemp(
            prefix="geoqc-job-",
            dir=str(settings.temporary_directory) if settings.temporary_directory else None,
        )
    )
    try:
        for name, content in components.items():
            (directory / name).write_bytes(content)
    except OSError:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    filenames = tuple(upload.name for upload in payload.files)
    requested_layer = payload.layer

    def operation() -> dict[str, object]:
        try:
            staged = GeospatialValidationRequest(
                files=[
                    UploadedFile(
                        name=name,
                        content_base64=base64.b64encode(
                            (directory / name.casefold()).read_bytes()
                        ).decode("ascii"),
                    )
                    for name in filenames
                ],
                layer=requested_layer,
            )
            return validate_payload(staged, settings).model_dump(mode="json")
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    try:
        record = manager.submit(REQUEST_ID.get(), operation)
    except JobQueueFullError as error:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(
            status_code=429,
            detail="The job queue is full; retry later.",
            headers={"Retry-After": "1"},
        ) from error
    except RuntimeError:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return JobCreationResponse(
        job_id=record.job_id,
        state="queued",
        status_url=f"/api/jobs/{record.job_id}",
        request_id=record.request_id,
    )


@router.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
def job_status(job_id: str, request: Request) -> JobStatusResponse:
    """Return a safe concurrent snapshot of one job."""
    if len(job_id) > 128:
        raise HTTPException(status_code=404, detail="Job not found.")
    manager: JobManager = request.app.state.job_manager
    record = manager.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JobStatusResponse(
        job_id=record.job_id,
        state=record.state.value,
        request_id=record.request_id,
        result=dict(record.result) if record.result is not None else None,
        error=record.error,
    )
