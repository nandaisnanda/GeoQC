"""FastAPI composition root with replaceable production controls."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

from geoqc import __version__
from geoqc.interfaces.api.geometry_routes import router as geometry_router
from geoqc.interfaces.api.job_routes import router as job_router
from geoqc.interfaces.api.jobs import JobManager
from geoqc.interfaces.api.metrics import MetricsRegistry
from geoqc.interfaces.api.operations import (
    configure_logging,
    default_rate_limiter,
    operational_middleware,
)
from geoqc.interfaces.api.rate_limit import FixedWindowRateLimiter
from geoqc.interfaces.api.settings import ApiSettings
from geoqc.interfaces.api.spatial_routes import router as spatial_router


def _prepare_temporary_directory(path: Path | None) -> None:
    if path is None:
        return
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError("temporary_directory must be a directory")


def create_app(
    settings: ApiSettings | None = None,
    *,
    rate_limiter: FixedWindowRateLimiter | None = None,
    metrics: MetricsRegistry | None = None,
    job_manager: JobManager | None = None,
) -> FastAPI:
    """Build an independently testable API application."""
    selected = settings or ApiSettings.from_env()
    _prepare_temporary_directory(selected.temporary_directory)
    configure_logging(selected.log_level)
    registry = metrics or MetricsRegistry()
    manager = job_manager or JobManager(
        workers=selected.job_workers,
        retention_seconds=selected.job_retention_seconds,
        metrics=registry,
    )

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        yield
        manager.close()

    application = FastAPI(
        title="GeoQC API",
        description="GIS quality-control API.",
        version=__version__,
        docs_url="/docs" if not selected.is_production else None,
        redoc_url="/redoc" if not selected.is_production else None,
        openapi_url="/openapi.json" if not selected.is_production else None,
        lifespan=lifespan,
    )
    application.state.settings = selected
    application.state.metrics = registry
    application.state.rate_limiter = rate_limiter or default_rate_limiter()
    application.state.job_manager = manager
    application.include_router(spatial_router)
    application.include_router(geometry_router)
    application.include_router(job_router)
    application.middleware("http")(operational_middleware)
    application.middleware("http")(add_security_headers)

    @application.get("/metrics", include_in_schema=False)
    def metrics_endpoint() -> Response:
        if not selected.metrics_enabled:
            return Response(status_code=404)
        return PlainTextResponse(registry.render(), media_type="text/plain; version=0.0.4")

    return application


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


app = create_app()
