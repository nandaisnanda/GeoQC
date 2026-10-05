"""Typed, validated configuration for the optional GeoQC HTTP service."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class EnvironmentMode(StrEnum):
    """Supported deployment modes."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


def _boolean(value: str, name: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return parsed


def _secrets(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """All process configuration required by API adapters."""

    environment: EnvironmentMode = EnvironmentMode.DEVELOPMENT
    authentication_enabled: bool = False
    api_keys: tuple[str, ...] = ()
    bearer_tokens: tuple[str, ...] = ()
    rate_limit_requests: int = 120
    rate_limit_expensive_requests: int = 20
    rate_limit_window_seconds: int = 60
    max_upload_bytes: int = 100 * 1024 * 1024
    max_features: int = 1_000_000
    max_reported_features: int = 1_000
    max_repair_features: int = 50_000
    temporary_directory: Path | None = None
    async_threshold_bytes: int = 10 * 1024 * 1024
    job_workers: int = 2
    job_retention_seconds: int = 3_600
    log_level: str = "INFO"
    metrics_enabled: bool = True
    streaming_chunk_size: int = 16_384

    def __post_init__(self) -> None:
        positive = (
            "rate_limit_requests",
            "rate_limit_expensive_requests",
            "rate_limit_window_seconds",
            "max_upload_bytes",
            "max_features",
            "max_reported_features",
            "max_repair_features",
            "async_threshold_bytes",
            "job_workers",
            "job_retention_seconds",
            "streaming_chunk_size",
        )
        for name in positive:
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be greater than zero")
        normalized_level = self.log_level.strip().upper()
        if normalized_level not in logging.getLevelNamesMapping():
            raise ValueError("log_level must be a standard logging level")
        object.__setattr__(self, "log_level", normalized_level)
        if any(not secret for secret in (*self.api_keys, *self.bearer_tokens)):
            raise ValueError("authentication secrets must not be empty")
        if self.environment is EnvironmentMode.PRODUCTION:
            if not self.authentication_enabled:
                raise ValueError("production requires authentication")
            if not self.api_keys and not self.bearer_tokens:
                raise ValueError("production requires an API key or bearer token")
            if min(len(item) for item in (*self.api_keys, *self.bearer_tokens)) < 16:
                raise ValueError("production authentication secrets must be at least 16 characters")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ApiSettings:
        """Parse settings from environment variables without exposing secrets."""
        values = os.environ if environ is None else environ
        mode = EnvironmentMode(values.get("GEOQC_ENVIRONMENT", "development").strip().casefold())
        auth_default = mode is EnvironmentMode.PRODUCTION
        temp_value = values.get("GEOQC_TEMPORARY_DIRECTORY", "").strip()
        return cls(
            environment=mode,
            authentication_enabled=_boolean(
                values.get("GEOQC_AUTH_ENABLED", str(auth_default)), "GEOQC_AUTH_ENABLED"
            ),
            api_keys=_secrets(values.get("GEOQC_API_KEYS", "")),
            bearer_tokens=_secrets(values.get("GEOQC_BEARER_TOKENS", "")),
            rate_limit_requests=_positive_int(
                values.get("GEOQC_RATE_LIMIT_REQUESTS", "120"), "GEOQC_RATE_LIMIT_REQUESTS"
            ),
            rate_limit_expensive_requests=_positive_int(
                values.get("GEOQC_RATE_LIMIT_EXPENSIVE_REQUESTS", "20"),
                "GEOQC_RATE_LIMIT_EXPENSIVE_REQUESTS",
            ),
            rate_limit_window_seconds=_positive_int(
                values.get("GEOQC_RATE_LIMIT_WINDOW_SECONDS", "60"),
                "GEOQC_RATE_LIMIT_WINDOW_SECONDS",
            ),
            max_upload_bytes=_positive_int(
                values.get("GEOQC_MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)),
                "GEOQC_MAX_UPLOAD_BYTES",
            ),
            max_features=_positive_int(
                values.get("GEOQC_MAX_FEATURES", "1000000"), "GEOQC_MAX_FEATURES"
            ),
            max_reported_features=_positive_int(
                values.get("GEOQC_MAX_REPORTED_FEATURES", "1000"),
                "GEOQC_MAX_REPORTED_FEATURES",
            ),
            max_repair_features=_positive_int(
                values.get("GEOQC_MAX_REPAIR_FEATURES", "50000"),
                "GEOQC_MAX_REPAIR_FEATURES",
            ),
            temporary_directory=Path(temp_value) if temp_value else None,
            async_threshold_bytes=_positive_int(
                values.get("GEOQC_ASYNC_THRESHOLD_BYTES", str(10 * 1024 * 1024)),
                "GEOQC_ASYNC_THRESHOLD_BYTES",
            ),
            job_workers=_positive_int(values.get("GEOQC_JOB_WORKERS", "2"), "GEOQC_JOB_WORKERS"),
            job_retention_seconds=_positive_int(
                values.get("GEOQC_JOB_RETENTION_SECONDS", "3600"),
                "GEOQC_JOB_RETENTION_SECONDS",
            ),
            log_level=values.get("GEOQC_LOG_LEVEL", "INFO"),
            metrics_enabled=_boolean(
                values.get("GEOQC_METRICS_ENABLED", "true"), "GEOQC_METRICS_ENABLED"
            ),
            streaming_chunk_size=_positive_int(
                values.get("GEOQC_STREAMING_CHUNK_SIZE", "16384"),
                "GEOQC_STREAMING_CHUNK_SIZE",
            ),
        )

    @property
    def max_encoded_upload_chars(self) -> int:
        return ((self.max_upload_bytes + 2) // 3) * 4

    @property
    def is_production(self) -> bool:
        return self.environment is EnvironmentMode.PRODUCTION


DEFAULT_SETTINGS = ApiSettings.from_env()
ENVIRONMENT = DEFAULT_SETTINGS.environment.value
IS_PRODUCTION = DEFAULT_SETTINGS.is_production
REQUIRED_SHAPEFILE_SUFFIXES = frozenset({".shp", ".shx", ".dbf"})
ALLOWED_SHAPEFILE_SUFFIXES = REQUIRED_SHAPEFILE_SUFFIXES | {".prj", ".cpg"}
SINGLE_FILE_DRIVERS: dict[str, frozenset[str]] = {
    ".geojson": frozenset({"GeoJSON"}),
    ".json": frozenset({"GeoJSON"}),
    ".gpkg": frozenset({"GPKG"}),
    ".fgb": frozenset({"FlatGeobuf"}),
    ".parquet": frozenset({"GeoParquet"}),
}
WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)
# Compatibility constants retained for request-model bounds and old imports.
MAX_DECODED_UPLOAD_BYTES = DEFAULT_SETTINGS.max_upload_bytes
MAX_ENCODED_UPLOAD_CHARS = DEFAULT_SETTINGS.max_encoded_upload_chars
MAX_FEATURES = DEFAULT_SETTINGS.max_features
MAX_REPORTED_FEATURES = DEFAULT_SETTINGS.max_reported_features
MAX_REPAIR_FEATURES = DEFAULT_SETTINGS.max_repair_features
STREAMING_CHUNK_SIZE = DEFAULT_SETTINGS.streaming_chunk_size
