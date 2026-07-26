"""Tests for the real PyProj datum transformation adapter."""

import pytest

from geoqc.domain.exceptions import DatumTransformationError
from geoqc.domain.models import GeographicBounds
from geoqc.infrastructure.gis import PyprojDatumTransformationInspector


def test_inspector_isolates_datum_from_projection_conversion() -> None:
    inspector = PyprojDatumTransformationInspector()
    points = ((106.0, -7.0), (108.0, -5.0))

    result = inspector.inspect(
        "EPSG:4326",
        "EPSG:3857",
        GeographicBounds(106, -7, 108, -5),
        points,
    )

    assert result.source_crs == "EPSG:4326"
    assert result.target_crs == "EPSG:4326"
    assert result.best_operation_available is True
    assert result.uses_ballpark_transformation is False
    assert result.missing_grids == ()
    assert [sample.displacement_m for sample in result.samples] == pytest.approx([0, 0])


def test_inspector_reports_missing_best_grid_for_nad27() -> None:
    result = PyprojDatumTransformationInspector().inspect(
        "EPSG:4267",
        "EPSG:4326",
        GeographicBounds(-125, 25, -66, 49),
        ((-100, 40),),
    )

    assert result.best_operation_available is False
    assert "us_noaa_conus.tif" in result.missing_grids
    assert result.declared_accuracy_m == 10.0
    assert result.samples[0].displacement_m > 1


def test_inspector_wraps_invalid_crs() -> None:
    with pytest.raises(DatumTransformationError):
        PyprojDatumTransformationInspector().inspect(
            "not-a-crs",
            "EPSG:4326",
            GeographicBounds(106, -7, 108, -5),
            ((107, -6),),
        )
