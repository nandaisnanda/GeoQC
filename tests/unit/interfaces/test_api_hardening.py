"""Focused production-hardening contracts for the optional API."""

import base64
import json
import logging
from pathlib import Path
from threading import Event, Thread
from time import monotonic

import geopandas as gpd  # type: ignore[import-untyped]
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Point

from geoqc.interfaces.api import job_routes
from geoqc.interfaces.api.app import create_app
from geoqc.interfaces.api.jobs import JobManager, JobState
from geoqc.interfaces.api.metrics import MetricsRegistry
from geoqc.interfaces.api.operations import JsonFormatter
from geoqc.interfaces.api.rate_limit import FixedWindowRateLimiter
from geoqc.interfaces.api.settings import ApiSettings, EnvironmentMode


def _settings(
    *,
    authentication_enabled: bool = False,
    api_keys: tuple[str, ...] = (),
    rate_limit_requests: int = 100,
    rate_limit_window_seconds: int = 60,
    temporary_directory: Path | None = None,
    max_features: int = 1_000_000,
    max_upload_bytes: int = 100 * 1024 * 1024,
) -> ApiSettings:
    return ApiSettings(
        environment=EnvironmentMode.TEST,
        authentication_enabled=authentication_enabled,
        api_keys=api_keys,
        rate_limit_requests=rate_limit_requests,
        rate_limit_expensive_requests=100,
        rate_limit_window_seconds=rate_limit_window_seconds,
        temporary_directory=temporary_directory,
        max_features=max_features,
        max_upload_bytes=max_upload_bytes,
    )


def _payload(path: Path) -> dict[str, object]:
    return {
        "files": [
            {
                "name": path.name,
                "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
            }
        ]
    }


def _dataset(path: Path, *, count: int = 1) -> None:
    gpd.GeoDataFrame(
        geometry=[Point(index, index) for index in range(count)], crs="EPSG:4326"
    ).to_file(path, driver="GeoJSON")


def _wait_for_terminal(client: TestClient, status_url: str) -> dict[str, object]:
    deadline = monotonic() + 5
    while monotonic() < deadline:
        payload = client.get(status_url).json()
        if payload["state"] in {"succeeded", "failed"}:
            return dict(payload)
    raise AssertionError("job did not reach a terminal state")


def test_authentication_is_disabled_locally_and_production_fails_closed() -> None:
    with TestClient(create_app(_settings())) as client:
        assert client.get("/openapi.json").status_code == 200
    with pytest.raises(ValueError, match="production requires authentication"):
        ApiSettings(environment=EnvironmentMode.PRODUCTION)
    with pytest.raises(ValueError, match="requires an API key"):
        ApiSettings(environment=EnvironmentMode.PRODUCTION, authentication_enabled=True)


def test_missing_and_invalid_credentials_are_distinct() -> None:
    settings = _settings(authentication_enabled=True, api_keys=("a-secure-api-key",))
    with TestClient(create_app(settings)) as client:
        missing = client.get("/metrics")
        invalid = client.get("/metrics", headers={"X-API-Key": "wrong"})
        valid = client.get("/metrics", headers={"X-API-Key": "a-secure-api-key"})
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"]
    assert invalid.status_code == 403
    assert valid.status_code == 200


def test_rate_limit_exhaustion_and_clock_recovery() -> None:
    now = [10.0]
    limiter = FixedWindowRateLimiter(clock=lambda: now[0])
    settings = _settings(rate_limit_requests=2, rate_limit_window_seconds=10)
    with TestClient(create_app(settings, rate_limiter=limiter)) as client:
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/openapi.json").status_code == 200
        limited = client.get("/openapi.json")
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "10"
        now[0] = 20.0
        assert client.get("/openapi.json").status_code == 200


def test_request_id_generation_propagation_and_log_redaction() -> None:
    with TestClient(create_app(_settings())) as client:
        generated = client.get("/metrics")
        accepted = client.get("/metrics", headers={"X-Request-ID": "client-request-42"})
    assert len(generated.headers["x-request-id"]) == 32
    assert accepted.headers["x-request-id"] == "client-request-42"

    record = logging.LogRecord("geoqc.api", logging.INFO, "", 0, "complete", (), None)
    record.request_id = "safe-id"
    record.authorization = "Bearer secret-token"
    record.filename = "private-dataset.gpkg"
    rendered = JsonFormatter().format(record)
    assert json.loads(rendered)["request_id"] == "safe-id"
    assert "secret-token" not in rendered
    assert "private-dataset" not in rendered


def test_metrics_have_bounded_labels() -> None:
    registry = MetricsRegistry()
    registry.observe_request("GET", "/user/supplied/value", 418, 0.25)
    rendered = registry.render()
    assert 'route="other"' in rendered
    assert "/user/supplied/value" not in rendered


def test_async_job_success_concurrent_reads_and_temporary_cleanup(tmp_path: Path) -> None:
    source = tmp_path / "points.geojson"
    temporary = tmp_path / "jobs"
    _dataset(source)
    settings = _settings(temporary_directory=temporary)
    with TestClient(create_app(settings)) as client:
        created = client.post("/api/jobs/geometry/validate", json=_payload(source))
        assert created.status_code == 202
        status_url = created.json()["status_url"]
        responses: list[int] = []
        threads = [
            Thread(target=lambda: responses.append(client.get(status_url).status_code))
            for _ in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        terminal = _wait_for_terminal(client, status_url)
        assert terminal["state"] == JobState.SUCCEEDED.value
        job_result = terminal["result"]
        assert isinstance(job_result, dict)
        assert job_result["feature_count"] == 1
        assert responses == [200, 200, 200, 200]
        assert list(temporary.iterdir()) == []


def test_async_job_failure_and_invalid_id_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("secret stack detail")

    monkeypatch.setattr(job_routes, "validate_payload", fail)
    payload = {"files": [{"name": "broken.geojson", "content_base64": "e30="}]}
    with TestClient(create_app(_settings())) as client:
        created = client.post("/api/jobs/geometry/validate", json=payload)
        terminal = _wait_for_terminal(client, created.json()["status_url"])
        missing = client.get("/api/jobs/not-a-real-job")
    assert terminal["state"] == JobState.FAILED.value
    assert terminal["error"] == "Job processing failed."
    assert "secret" not in json.dumps(terminal)
    assert missing.status_code == 404


def test_job_state_transitions_and_retention_cleanup() -> None:
    clock = [100.0]
    started = Event()
    release = Event()
    manager = JobManager(
        workers=1,
        retention_seconds=10,
        metrics=MetricsRegistry(),
        clock=lambda: clock[0],
    )

    def operation() -> dict[str, object]:
        started.set()
        assert release.wait(timeout=2)
        return {"ok": True}

    record = manager.submit("request-1", operation)
    assert record.state is JobState.QUEUED
    assert started.wait(timeout=2)
    running = manager.get(record.job_id)
    assert running is not None and running.state is JobState.RUNNING
    release.set()
    deadline = monotonic() + 2
    terminal = manager.get(record.job_id)
    while terminal is not None and terminal.state is not JobState.SUCCEEDED:
        assert monotonic() < deadline
        terminal = manager.get(record.job_id)
    assert terminal is not None and terminal.result == {"ok": True}
    clock[0] = 111.0
    assert manager.cleanup() == 1
    assert manager.get(record.job_id) is None
    manager.close()


def test_configured_upload_and_feature_limits(tmp_path: Path) -> None:
    source = tmp_path / "two.geojson"
    _dataset(source, count=2)
    with TestClient(create_app(_settings(max_features=1))) as client:
        response = client.post("/api/geometry/validate", json=_payload(source))
    assert response.status_code == 413

    oversized = {"files": [{"name": "large.geojson", "content_base64": "AAAA"}]}
    with TestClient(create_app(_settings(max_upload_bytes=1))) as client:
        response = client.post("/api/geometry/validate", json=oversized)
    assert response.status_code == 413


def test_archives_and_traversal_members_are_not_accepted() -> None:
    payload = {"files": [{"name": "../malicious.zip", "content_base64": "UEsDBAoAAAAAAA=="}]}
    with TestClient(create_app(_settings())) as client:
        response = client.post("/api/geometry/validate", json=payload)
    assert response.status_code == 400
    assert "Unsafe filename" in response.json()["detail"]
    payload["files"] = [{"name": "malicious.zip", "content_base64": "UEsDBAoAAAAAAA=="}]
    with TestClient(create_app(_settings())) as client:
        response = client.post("/api/geometry/validate", json=payload)
    assert response.status_code == 400
    assert "Unsupported extension" in response.json()["detail"]
