"""Tests for datum-shift domain value objects."""

import pytest

from geoqc.domain.models import (
    DatumShiftAuditResult,
    DatumShiftSample,
    DatumShiftStatus,
    DatumTransformationEvidence,
    GeographicBounds,
    TransformationQuality,
)


@pytest.mark.parametrize(
    "bounds",
    [
        (-181, -5, 110, 5),
        (110, -5, 110, 5),
        (110, -91, 120, 5),
        (110, 5, 120, 5),
        (float("nan"), -5, 120, 5),
    ],
)
def test_geographic_bounds_reject_invalid_aoi(bounds: tuple[float, ...]) -> None:
    with pytest.raises(ValueError, match="AOI"):
        GeographicBounds(*bounds)


def test_result_exposes_only_samples_above_threshold() -> None:
    normal = DatumShiftSample(0, 0, 0, 0, 5.0)
    abnormal = DatumShiftSample(1, 1, 1, 1, 5.01)
    evidence = DatumTransformationEvidence(
        "SOURCE",
        "TARGET",
        "operation",
        1.0,
        True,
        False,
        (),
        (normal, abnormal),
    )
    result = DatumShiftAuditResult(
        DatumShiftStatus.ABNORMAL,
        TransformationQuality.RELIABLE,
        5.0,
        evidence,
        5.01,
        5.005,
        "summary",
        (),
        "recommendation",
    )

    assert result.abnormal_samples == (abnormal,)
