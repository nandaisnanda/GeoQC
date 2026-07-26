"""Tests for axis-order domain value objects."""

import pytest

from geoqc.domain.models import AxisOrderAuditResult, AxisOrderStatus, CoordinateBounds


@pytest.mark.parametrize(
    "bounds",
    [
        (0, 0, 0, 1),
        (0, 1, 1, 1),
        (2, 0, 1, 1),
        (0, 2, 1, 1),
        (float("nan"), 0, 1, 1),
    ],
)
def test_coordinate_bounds_reject_invalid_extent(bounds: tuple[float, ...]) -> None:
    with pytest.raises(ValueError, match="bounds"):
        CoordinateBounds(*bounds)


def test_result_exposes_swapped_convenience_flag() -> None:
    observed = CoordinateBounds(-7, 106, -5, 108)
    result = AxisOrderAuditResult(
        AxisOrderStatus.LIKELY_SWAPPED,
        observed,
        None,
        None,
        None,
        None,
        None,
        "summary",
        "recommendation",
    )

    assert result.axes_likely_swapped is True
