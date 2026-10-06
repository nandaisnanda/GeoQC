"""Cross-cutting HTTP operations: identity, auth, rate limits, logs, and metrics."""

import json
import logging
import re
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from ipaddress import ip_address
from time import monotonic
from uuid import uuid4

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from geoqc.interfaces.api.authentication import authenticate
from geoqc.interfaces.api.metrics import MetricsRegistry
from geoqc.interfaces.api.rate_limit import FixedWindowRateLimiter, InMemoryRateLimitStorage
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


class RequestBodyTooLargeError(RuntimeError):
    """Raised while streaming a request body beyond the configured bound."""


class RequestSizeLimitMiddleware:
    """Bound streaming request bodies even when Content-Length is absent or false."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        received_bytes = 0

        async def receive_bounded() -> Message:
            nonlocal received_bytes
            message = await receive()
            body = message.get("body", b"")
            if isinstance(body, bytes):
                received_bytes += len(body)
            if received_bytes > self._max_bytes:
                raise RequestBodyTooLargeError
            return message

        await self._app(scope, receive_bounded, send)


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


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the safe API error shape while retaining legacy ``detail``."""
    return JSONResponse(
        {
            "error_code": code,
            "message": message,
            "request_id": request_id,
            "detail": message,
        },
        status_code=status_code,
        headers=headers,
    )


def _client_identity(request: Request, settings: ApiSettings) -> str:
    host = request.client.host if request.client is not None else "unknown"
    if settings.trust_proxy_headers and host in settings.trusted_proxy_addresses:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", maxsplit=1)[0].strip()
        try:
            return f"client:{ip_address(forwarded)}"
        except ValueError:
            pass
    try:
        return f"client:{ip_address(host)}"
    except ValueError:
        return "client:unknown"


async def operational_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Apply production controls while preserving response compatibility."""
    settings: ApiSettings = request.app.state.settings
    metrics: MetricsRegistry = request.app.state.metrics
    request_id = _request_id(request)
    request.state.request_id = request_id
    token = REQUEST_ID.set(request_id)
    started = monotonic()
    try:
        response = await _authorize_and_dispatch(request, call_next, settings, metrics, request_id)
    except RequestBodyTooLargeError:
        response = error_response(
            status_code=413,
            code="request_too_large",
            message="The request exceeds the configured size limit.",
            request_id=request_id,
        )
    except Exception:
        LOGGER.exception(
            "unhandled_request_failure",
            extra={"request_id": request_id, "method": request.method, "route": "other"},
        )
        response = error_response(
            status_code=500,
            code="internal_error",
            message="Unexpected internal failure.",
            request_id=request_id,
        )
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


async def _authorize_and_dispatch(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
    settings: ApiSettings,
    metrics: MetricsRegistry,
    request_id: str,
) -> Response:
    auth = authenticate(request, settings)
    if not auth.authenticated:
        status = 403 if auth.credential_present else 401
        return error_response(
            status_code=status,
            code="invalid_credential" if status == 403 else "authentication_required",
            message="Invalid credential." if status == 403 else "Authentication required.",
            request_id=request_id,
            headers={"WWW-Authenticate": "Bearer, X-API-Key"} if status == 401 else None,
        )

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            request_bytes = int(content_length)
        except ValueError:
            return error_response(
                status_code=400,
                code="invalid_content_length",
                message="Content-Length must be a non-negative integer.",
                request_id=request_id,
            )
        if request_bytes < 0:
            return error_response(
                status_code=400,
                code="invalid_content_length",
                message="Content-Length must be a non-negative integer.",
                request_id=request_id,
            )
        if request_bytes > settings.max_request_bytes:
            return error_response(
                status_code=413,
                code="request_too_large",
                message="The request exceeds the configured size limit.",
                request_id=request_id,
            )

    identity = auth.principal_key or _client_identity(request, settings)
    expensive = request.url.path in _EXPENSIVE_PATHS
    limit = settings.rate_limit_expensive_requests if expensive else settings.rate_limit_requests
    bucket = "expensive" if expensive else "standard"
    decision = request.app.state.rate_limiter.check(
        f"{identity}:{bucket}",
        limit=limit,
        window_seconds=settings.rate_limit_window_seconds,
    )
    if not decision.allowed:
        metrics.event("rate_limit_rejected")
        return error_response(
            status_code=429,
            code="rate_limit_exceeded",
            message="Rate limit exceeded.",
            request_id=request_id,
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )
    response = await call_next(request)
    response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
    return response


def default_rate_limiter(settings: ApiSettings) -> FixedWindowRateLimiter:
    return FixedWindowRateLimiter(
        InMemoryRateLimitStorage(max_entries=settings.rate_limit_max_identities)
    )
