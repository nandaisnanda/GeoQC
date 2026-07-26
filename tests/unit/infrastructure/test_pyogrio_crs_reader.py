"""Tests for the metadata-only pyogrio CRS adapter."""

from typing import Any

import pytest

from geoqc.domain.exceptions import DatasetMetadataReadError
from geoqc.domain.models import DatasetSource
from geoqc.infrastructure.gis import PyogrioCrsMetadataReader


def test_reader_normalizes_authority_crs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_read_info(uri: str, *, layer: str | None) -> dict[str, Any]:
        captured.update(uri=uri, layer=layer)
        return {"crs": "EPSG:4326"}

    monkeypatch.setattr(
        "geoqc.infrastructure.gis.pyogrio_crs_reader.pyogrio.read_info", fake_read_info
    )
    source = DatasetSource("data.gpkg", "roads")

    result = PyogrioCrsMetadataReader().read(source)

    assert captured == {"uri": "data.gpkg", "layer": "roads"}
    assert result.crs is not None
    assert result.crs.authority == "EPSG:4326"
    assert result.crs.display_name == "EPSG:4326"
    assert "GEOGCRS" in result.crs.canonical_wkt


def test_reader_returns_none_for_missing_crs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "geoqc.infrastructure.gis.pyogrio_crs_reader.pyogrio.read_info",
        lambda uri, layer=None: {"crs": None},
    )

    result = PyogrioCrsMetadataReader().read(DatasetSource("data.geojson"))

    assert result.crs is None


def test_reader_wraps_invalid_crs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "geoqc.infrastructure.gis.pyogrio_crs_reader.pyogrio.read_info",
        lambda uri, layer=None: {"crs": "not-a-real-crs"},
    )

    with pytest.raises(DatasetMetadataReadError, match="Invalid CRS metadata"):
        PyogrioCrsMetadataReader().read(DatasetSource("invalid.geojson"))


def test_reader_wraps_dataset_access_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(uri: str, *, layer: str | None) -> dict[str, Any]:
        raise OSError("file not found")

    monkeypatch.setattr("geoqc.infrastructure.gis.pyogrio_crs_reader.pyogrio.read_info", fail)

    with pytest.raises(DatasetMetadataReadError, match="file not found"):
        PyogrioCrsMetadataReader().read(DatasetSource("missing.gpkg"))
