"""The deprecated dataset entry points warn with a removal version."""

import warnings
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import pytest
from shapely.geometry import Point

import geoqc


@pytest.fixture
def points_path(tmp_path: Path) -> Path:
    source = tmp_path / "points.geojson"
    gpd.GeoDataFrame({"id": [1, 2]}, geometry=[Point(1, 2), Point(1, 2)], crs="EPSG:4326").to_file(
        source, driver="GeoJSON"
    )
    return source


def test_audit_file_warns_with_removal_version_and_matches_audit_dataset(
    points_path: Path,
) -> None:
    with pytest.warns(DeprecationWarning, match="audit_file\(\) is deprecated") as caught:
        legacy = geoqc.audit_file(points_path, preset=geoqc.QualityPreset.POINT_SURVEY)

    message = str(caught[0].message)
    assert "0.3.0" in message
    assert "audit_dataset" in message
    assert caught[0].filename == __file__
    canonical = geoqc.audit_dataset(points_path, preset=geoqc.QualityPreset.POINT_SURVEY)
    assert [issue.code for issue in legacy.issues] == [issue.code for issue in canonical.issues]
    assert legacy.quality_score == canonical.quality_score


def test_run_quality_workflow_warns_with_removal_version(points_path: Path) -> None:
    profile = geoqc.QualityProfile(name="survey", preset=geoqc.QualityPreset.POINT_SURVEY)

    with pytest.warns(DeprecationWarning, match="run_quality_workflow\(\) is deprecated") as caught:
        geoqc.run_quality_workflow(points_path, profile=profile)

    message = str(caught[0].message)
    assert "0.3.0" in message
    assert "audit_dataset" in message
    assert caught[0].filename == __file__


def test_canonical_audit_dataset_does_not_warn(points_path: Path) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        geoqc.audit_dataset(points_path, preset=geoqc.QualityPreset.POINT_SURVEY)
