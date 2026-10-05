"""Cross-cutting HTTP operations: identity, auth, rate limits, logs, and metrics."""

import json
import logging
import re
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from time import monotonic
from uuid import uuid4

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from geoqc.interfaces.api.authentication import authenticate
from geoqc.interfaces.api.metrics import MetricsRegistry
from geoqc.interfaces.api.rate_limit import FixedWindowRateLimiter
from geoqc.interfaces.api.settings import ApiSettings

LOGGER = logging.getLogger("geoqc.api")
REQUEST_ID: ContextVar[str] = ContextVar("geoqc_request_id", default="")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_EXPENSIVE_PATHS = frozenset(
    {
        "/api/geometry/validate",
        "/api/geometry/validate-shapefile",
        "/api/geometry/repair",
        "/api/jobs/geometry/validate",
    }
)


class JsonFormatter(logging.Formatter):
    """Render records as structured JSON using an allowlist of safe fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in ("request_id", "method", "route", "status", "duration_ms"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    LOGGER.handlers[:] = [handler]
    LOGGER.setLevel(level)
    LOGGER.propagate = False


def _request_id(request: Request) -> str:
    candidate = request.headers.get("x-request-id", "")
    return candidate if _REQUEST_ID.fullmatch(candidate) else uuid4().hex


async def operational_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Apply production controls while preserving response compatibility."""
    settings: ApiSettings = request.app.state.settings
    metrics: MetricsRegistry = request.app.state.metrics
    request_id = _request_id(request)
    token = REQUEST_ID.set(request_id)
    started = monotonic()
    response: Response
    try:
        auth = authenticate(request, settings)
        if not auth.authenticated:
            status = 403 if auth.credential_present else 401
            headers = {"WWW-Authenticate": "Bearer, X-API-Key"} if status == 401 else {}
            response = JSONResponse(
                {"detail": "Authentication required." if status == 401 else "Invalid credential."},
                status_code=status,
                headers=headers,
            )
        else:
            client = request.client.host if request.client is not None else "unknown"
            expensive = request.url.path in _EXPENSIVE_PATHS
            limit = (
                settings.rate_limit_expensive_requests
                if expensive
                else settings.rate_limit_requests
            )
            bucket = "expensive" if expensive else "standard"
            decision = request.app.state.rate_limiter.check(
                f"{client}:{bucket}",
                limit=limit,
                window_seconds=settings.rate_limit_window_seconds,
            )
            if not decision.allowed:
                response = JSONResponse(
                    {"detail": "Rate limit exceeded."},
                    status_code=429,
                    headers={"Retry-After": str(decision.retry_after_seconds)},
                )
            else:
                response = await call_next(request)
                response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
    except Exception:
        LOGGER.exception(
            "unhandled_request_failure",
            extra={"request_id": request_id, "method": request.method, "route": "other"},
        )
        response = JSONResponse({"detail": "Unexpected internal failure."}, status_code=500)
    finally:
        REQUEST_ID.reset(token)
    duration = monotonic() - started
    route = getattr(request.scope.get("route"), "path", request.url.path)
    response.headers["X-Request-ID"] = request_id
    metrics.observe_request(request.method, route, response.status_code, duration)
    if response.status_code == 413:
        metrics.event("upload_rejected")
    if route in {"/api/geometry/validate", "/api/geometry/validate-shapefile"}:
        metrics.event("audit_succeeded" if response.status_code < 400 else "audit_failed")
    LOGGER.info(
        "request_complete",
        extra={
            "request_id": request_id,
            "method": request.method,
            "route": MetricsRegistry.route_label(route),
            "status": response.status_code,
            "duration_ms": round(duration * 1000, 3),
        },
    )
    return response


def default_rate_limiter() -> FixedWindowRateLimiter:
    return FixedWindowRateLimiter()
