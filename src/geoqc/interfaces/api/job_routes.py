"""HTTP adapter for process-local dataset validation jobs."""

from fastapi import APIRouter, HTTPException, Request, status

from geoqc.interfaces.api.geometry_routes import validate_payload
from geoqc.interfaces.api.jobs import JobManager
from geoqc.interfaces.api.operations import REQUEST_ID
from geoqc.interfaces.api.request_models import (
    GeospatialValidationRequest,
    JobCreationResponse,
    JobStatusResponse,
)
from geoqc.interfaces.api.settings import ApiSettings

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
    # Pydantic models are immutable enough for read-only worker use, but a
    # deep copy makes the thread ownership explicit.
    job_payload = payload.model_copy(deep=True)
    record = manager.submit(
        REQUEST_ID.get(),
        lambda: validate_payload(job_payload, settings).model_dump(mode="json"),
    )
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
