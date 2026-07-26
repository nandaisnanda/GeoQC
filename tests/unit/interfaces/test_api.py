"""Tests for the FastAPI composition root."""

import base64
from pathlib import Path

import geopandas  # type: ignore[import-untyped]
import pyogrio  # type: ignore[import-untyped]
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon
from starlette.routing import BaseRoute

from geoqc.interfaces.api.main import app

CLIENT = TestClient(app)


def test_api_metadata() -> None:
    """The API application exposes stable package metadata."""
    assert app.title == "GeoQC API"
    assert app.version == "0.1.0"


def test_api_responses_include_security_headers() -> None:
    """Browser-facing responses include defense-in-depth headers."""
    response = CLIENT.get("/openapi.json")

    assert response.headers["content-security-policy"] == (
        "default-src 'none'; frame-ancestors 'none'"
    )
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_api_exposes_geometry_validation_route() -> None:
    """The composition root exposes the generic geospatial use case."""
    documented_paths = {
        route_path for route in app.routes if (route_path := _route_path(route)) is not None
    }
    assert documented_paths == {
        "/api/geometry/repair",
        "/api/geometry/validate",
        "/api/geometry/validate-shapefile",
        "/api/repairs/prioritize",
        "/api/spatial/compare",
        "/api/spatial/conflicts",
        "/api/spatial/duplicates",
        "/docs",
        "/docs/oauth2-redirect",
        "/openapi.json",
        "/redoc",
    }


def test_enterprise_spatial_api_contracts() -> None:
    """Enterprise endpoints expose similarity, differences, severity, and priorities."""
    square = "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"
    duplicates = CLIENT.post(
        "/api/spatial/duplicates", json={"geometries_wkt": [square, square]}
    )
    comparison = CLIENT.post(
        "/api/spatial/compare",
        json={
            "left": {"name": "old", "geometries_wkt": [square], "crs": "EPSG:4326"},
            "right": {"name": "new", "geometries_wkt": [square], "crs": "EPSG:4326"},
        },
    )
    conflicts = CLIENT.post(
        "/api/spatial/conflicts",
        json={
            "layers": [
                {"name": "roads", "role": "road", "geometries_wkt": ["LINESTRING (0 0, 1 1)"]},
                {"name": "rivers", "role": "river", "geometries_wkt": ["LINESTRING (0 1, 1 0)"]},
            ]
        },
    )
    priorities = CLIENT.post(
        "/api/repairs/prioritize",
        json={
            "candidates": [
                {
                    "issue_id": "c-1",
                    "issue_type": "building_in_river",
                    "severity": 90,
                    "impact": 80,
                    "area": 10,
                    "feature_count": 2,
                }
            ]
        },
    )

    assert duplicates.status_code == 200
    assert duplicates.json()["pairs"][0]["similarity_percent"] == 100.0
    assert comparison.status_code == 200
    assert comparison.json()["crs_equal"] is True
    assert conflicts.status_code == 200
    assert conflicts.json()["conflicts"][0]["severity_score"] > 0
    assert priorities.status_code == 200
    assert priorities.json()["recommendations"][0]["rank"] == 1


def test_repair_geojson_returns_preview_and_preserves_attributes(tmp_path: Path) -> None:
    """Repair preview includes before/after snapshots and source attributes."""
    dataset = tmp_path / "sample.geojson"
    frame = geopandas.GeoDataFrame(
        {"name": ["bowtie"]},
        geometry=[Polygon([(0, 0), (2, 2), (0, 2), (2, 0)])],
        crs="EPSG:4326",
    )
    pyogrio.write_dataframe(frame, dataset, driver="GeoJSON")

    response = CLIENT.post(
        "/api/geometry/repair",
        json={"files": [_encoded_file(dataset)], "mode": "preview"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "preview"
    assert payload["repaired"] == 1
    assert payload["findings"][0]["before_wkt"] != payload["findings"][0]["after_wkt"]
    assert '"name": "bowtie"' in payload["original_geojson"]
    assert '"name": "bowtie"' in payload["repaired_geojson"]


def test_validate_shapefile_reports_invalid_features(tmp_path: Path) -> None:
    """Uploaded shapefile components are read and validated per feature."""
    shapefile = tmp_path / "sample.shp"
    frame = geopandas.GeoDataFrame(
        {"name": ["valid", "invalid"]},
        geometry=[
            Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]),
            Polygon([(0, 0), (2, 2), (0, 2), (2, 0)]),
        ],
        crs="EPSG:4326",
    )
    pyogrio.write_dataframe(frame, shapefile)
    files = []
    for component in tmp_path.glob("sample.*"):
        files.append(
            {
                "name": component.name,
                "content_base64": base64.b64encode(component.read_bytes()).decode("ascii"),
            }
        )

    response = TestClient(app).post(
        "/api/geometry/validate-shapefile",
        json={"files": files},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["feature_count"] == 2
    assert payload["invalid_feature_count"] == 1
    assert payload["issue_counts"]["invalid_geometry"] == 1
    assert payload["issue_counts"]["self_intersection"] == 1


def test_validate_shapefile_requires_sidecars() -> None:
    """An SHP file alone is rejected with an actionable message."""
    response = TestClient(app).post(
        "/api/geometry/validate-shapefile",
        json={"files": [{"name": "sample.shp", "content_base64": "AA=="}]},
    )

    assert response.status_code == 400
    assert "Missing required component" in response.json()["detail"]


@pytest.mark.parametrize(
    ("suffix", "driver"),
    [(".geojson", "GeoJSON"), (".gpkg", "GPKG"), (".fgb", "FlatGeobuf")],
)
def test_validate_supported_single_file_formats(tmp_path: Path, suffix: str, driver: str) -> None:
    """Single-file OGR formats use the same geometry validation pipeline."""
    dataset = tmp_path / f"sample{suffix}"
    frame = geopandas.GeoDataFrame(
        {"name": ["invalid"]},
        geometry=[Polygon([(0, 0), (2, 2), (0, 2), (2, 0)])],
        crs="EPSG:4326",
    )
    pyogrio.write_dataframe(frame, dataset, driver=driver)

    response = CLIENT.post(
        "/api/geometry/validate",
        json={"files": [_encoded_file(dataset)]},
    )

    assert response.status_code == 200
    assert response.json()["invalid_feature_count"] == 1


def test_validate_geopackage_requires_layer_when_ambiguous(tmp_path: Path) -> None:
    """A multi-layer container is never resolved by an implicit first-layer choice."""
    dataset = tmp_path / "sample.gpkg"
    frame = geopandas.GeoDataFrame(
        {"name": ["valid"]},
        geometry=[Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])],
        crs="EPSG:4326",
    )
    pyogrio.write_dataframe(frame, dataset, layer="first", driver="GPKG")
    pyogrio.write_dataframe(frame, dataset, layer="second", driver="GPKG", append=True)

    ambiguous = CLIENT.post(
        "/api/geometry/validate",
        json={"files": [_encoded_file(dataset)]},
    )
    selected = CLIENT.post(
        "/api/geometry/validate",
        json={"files": [_encoded_file(dataset)], "layer": "second"},
    )

    assert ambiguous.status_code == 400
    assert "multiple layers" in ambiguous.json()["detail"]
    assert selected.status_code == 200
    assert selected.json()["layer"] == "second"


@pytest.mark.parametrize(
    "filename",
    ["../sample.geojson", "folder/sample.geojson", "C:sample.geojson", "CON.geojson"],
)
def test_validate_rejects_unsafe_filenames(filename: str) -> None:
    """Uploaded names cannot escape or exploit the temporary directory on Windows."""
    response = CLIENT.post(
        "/api/geometry/validate",
        json={"files": [{"name": filename, "content_base64": "e30="}]},
    )

    assert response.status_code == 400
    assert "Unsafe filename" in response.json()["detail"]


def test_validate_rejects_extension_content_mismatch(tmp_path: Path) -> None:
    """The detected GDAL driver must match the allowlisted filename extension."""
    geojson = tmp_path / "actual.geojson"
    disguised = tmp_path / "disguised.fgb"
    frame = geopandas.GeoDataFrame(geometry=[], crs="EPSG:4326")
    pyogrio.write_dataframe(frame, geojson, driver="GeoJSON")
    disguised.write_bytes(geojson.read_bytes())

    response = CLIENT.post(
        "/api/geometry/validate",
        json={"files": [_encoded_file(disguised)]},
    )

    assert response.status_code == 422
    assert "does not match" in response.json()["detail"]


def test_validate_rejects_xml_based_formats() -> None:
    """Formats able to resolve external XML references are outside the safe allowlist."""
    response = CLIENT.post(
        "/api/geometry/validate",
        json={"files": [{"name": "remote-reference.kml", "content_base64": "e30="}]},
    )

    assert response.status_code == 400
    assert "Unsupported extension" in response.json()["detail"]


def test_validate_rejects_unknown_request_fields() -> None:
    """Unexpected request fields fail closed instead of being silently ignored."""
    response = CLIENT.post(
        "/api/geometry/validate",
        json={
            "files": [{"name": "sample.geojson", "content_base64": "e30="}],
            "unexpected": True,
        },
    )

    assert response.status_code == 422


def test_validate_does_not_expose_reader_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GDAL and filesystem exception details stay in server logs."""
    secret = "sensitive-local-path"

    def fail_read_info(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(pyogrio, "read_info", fail_read_info)
    response = CLIENT.post(
        "/api/geometry/validate",
        json={"files": [{"name": "sample.geojson", "content_base64": "e30="}]},
    )

    assert response.status_code == 422
    assert secret not in response.json()["detail"]


def _encoded_file(path: Path) -> dict[str, str]:
    """Encode one fixture file using the browser API contract."""
    return {
        "name": path.name,
        "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
    }


def _route_path(route: BaseRoute) -> str | None:
    """Read a route path without assuming all Starlette route subtypes expose it."""
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else None
