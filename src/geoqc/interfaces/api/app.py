"""FastAPI composition root and security middleware."""

import logging
import os
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from geoqc import __version__
from geoqc.interfaces.api.geometry_routes import router as geometry_router
from geoqc.interfaces.api.settings import IS_PRODUCTION
from geoqc.interfaces.api.spatial_routes import router as spatial_router

logging.basicConfig(level=os.environ.get("GEOQC_LOG_LEVEL", "INFO").strip().upper())

app: FastAPI = FastAPI(
    title="GeoQC API",
    description="GIS quality-control API.",
    version=__version__,
    docs_url="/docs" if not IS_PRODUCTION else None,
    redoc_url="/redoc" if not IS_PRODUCTION else None,
    openapi_url="/openapi.json" if not IS_PRODUCTION else None,
)
app.include_router(spatial_router)
app.include_router(geometry_router)


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
