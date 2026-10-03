"""Integration coverage for the public dataset-level audit workflow."""

import json
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import pytest
from shapely.geometry import Point

import geoqc


def test_public_audit_dataset_combines_services_and_explicit_skips(tmp_path: Path) -> None:
    source = tmp_path / "points.gpkg"
    gpd.GeoDataFrame(
        {"id": [1, 1], "name": ["one", "two"]},
        geometry=[Point(0, 0), Point(1, 1)],
        crs="EPSG:3857",
    ).to_file(source, layer="points", driver="GPKG")
    schema = geoqc.AttributeSchema(
        (
            geoqc.AttributeColumnSchema("id", geoqc.AttributeDataType.INTEGER, False),
            geoqc.AttributeColumnSchema("name", geoqc.AttributeDataType.STRING, False),
        ),
        id_column="id",
    )

    report = geoqc.audit_dataset(source, layer=None, schema=schema, checks="all")

    assert report.metadata.layer == "points"
    assert report.metadata.feature_count == 2
    assert report.check("geometry").status is geoqc.CheckStatus.PASSED
    assert report.check("crs").status is geoqc.CheckStatus.PASSED
    assert report.check("attributes").status is geoqc.CheckStatus.FAILED
    assert report.check("attributes").feature_indices == (0, 1)
    assert report.check("topology").status is geoqc.CheckStatus.SKIPPED
    assert report.check("topology").reason
    assert report.check("spatial").reason
    assert json.dumps(report.to_dict(), sort_keys=False) == json.dumps(
        report.to_dict(), sort_keys=False
    )


def test_missing_crs_skips_dependent_checks_with_actionable_reason(tmp_path: Path) -> None:
    source = tmp_path / "unknown.gpkg"
    gpd.GeoDataFrame({"id": [1]}, geometry=[Point(0, 0)]).to_file(source, driver="GPKG")

    report = geoqc.audit_dataset(source)

    assert report.check("crs").status is geoqc.CheckStatus.FAILED
    assert "projected CRS" in report.check("crs").issues[0].recommendation
    assert report.check("topology").status is geoqc.CheckStatus.SKIPPED
    assert "CRS is missing" in (report.check("topology").reason or "")
    assert report.check("spatial").status is geoqc.CheckStatus.SKIPPED


def test_check_selection_is_explicit_and_invalid_names_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "selected.gpkg"
    gpd.GeoDataFrame(geometry=[Point(0, 0)], crs="EPSG:3857").to_file(source, driver="GPKG")

    report = geoqc.audit_dataset(source, checks=("geometry",))

    assert report.check("geometry").status is geoqc.CheckStatus.PASSED
    assert report.check("crs").status is geoqc.CheckStatus.SKIPPED
    assert "not selected" in (report.check("crs").reason or "")
    with pytest.raises(ValueError, match="unknown audit checks"):
        geoqc.audit_dataset(source, checks=("imaginary",))
