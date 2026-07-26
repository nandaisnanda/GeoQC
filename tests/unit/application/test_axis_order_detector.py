"""Tests for bounding-box based axis-order detection."""

import pytest

from geoqc.application.services import AxisOrderDetector
from geoqc.domain.models import AxisOrderStatus, CoordinateBounds, GeographicBounds

INDONESIA = GeographicBounds(95, -11, 141, 6)


def test_detects_correct_longitude_latitude_from_ranges() -> None:
    result = AxisOrderDetector().detect(CoordinateBounds(106, -7, 108, -5))

    assert result.status is AxisOrderStatus.CORRECT
    assert result.declared_bounds == GeographicBounds(106, -7, 108, -5)
    assert result.swapped_bounds is None
    assert result.declared_spatial_match is None
    assert "konsisten" in result.summary


def test_detects_likely_swapped_latitude_longitude_from_ranges() -> None:
    result = AxisOrderDetector().detect(CoordinateBounds(-7, 106, -5, 108))

    assert result.status is AxisOrderStatus.LIKELY_SWAPPED
    assert result.declared_bounds is None
    assert result.swapped_bounds == GeographicBounds(106, -7, 108, -5)
    assert result.axes_likely_swapped is True
    assert "tukar axis" in result.recommendation


def test_uses_expected_bounds_to_resolve_numerically_ambiguous_axes() -> None:
    observed = CoordinateBounds(-6.3, 106.7, -6.1, 106.9)

    result = AxisOrderDetector().detect(observed, expected=INDONESIA)

    assert result.status is AxisOrderStatus.LIKELY_SWAPPED
    assert result.declared_spatial_match is False
    assert result.swapped_spatial_match is True


def test_reports_ambiguous_when_both_interpretations_are_plausible() -> None:
    result = AxisOrderDetector().detect(CoordinateBounds(10, 20, 11, 21))

    assert result.status is AxisOrderStatus.AMBIGUOUS
    assert result.declared_bounds is not None
    assert result.swapped_bounds is not None
    assert "expected geographic bounds" in result.recommendation


def test_expected_bounds_confirm_declared_order() -> None:
    result = AxisOrderDetector().detect(
        CoordinateBounds(106, -7, 108, -5),
        expected=INDONESIA,
    )

    assert result.status is AxisOrderStatus.CORRECT
    assert result.declared_spatial_match is True
    assert result.swapped_spatial_match is False


def test_expected_bounds_keep_result_ambiguous_when_both_orders_overlap() -> None:
    result = AxisOrderDetector().detect(
        CoordinateBounds(10, 20, 11, 21),
        expected=GeographicBounds(0, 0, 30, 30),
    )

    assert result.status is AxisOrderStatus.AMBIGUOUS
    assert result.declared_spatial_match is True
    assert result.swapped_spatial_match is True


def test_reports_invalid_when_neither_interpretation_is_geographic() -> None:
    result = AxisOrderDetector().detect(CoordinateBounds(200, 100, 210, 110))

    assert result.status is AxisOrderStatus.INVALID
    assert result.declared_bounds is None
    assert result.swapped_bounds is None


def test_reports_spatial_mismatch_instead_of_claiming_axis_swap() -> None:
    europe = CoordinateBounds(2, 48, 3, 49)

    result = AxisOrderDetector().detect(europe, expected=INDONESIA)

    assert result.status is AxisOrderStatus.INVALID
    assert result.declared_spatial_match is False
    assert result.swapped_spatial_match is False
    assert "area cakupan" in result.recommendation


@pytest.mark.parametrize(
    "observed",
    [
        CoordinateBounds(100, -10, 110, 0),
        CoordinateBounds(-10, 100, 0, 110),
    ],
)
def test_touching_expected_boundary_is_not_a_spatial_overlap(
    observed: CoordinateBounds,
) -> None:
    expected = GeographicBounds(110, -10, 120, 0)

    result = AxisOrderDetector().detect(observed, expected=expected)

    assert result.status is AxisOrderStatus.INVALID
