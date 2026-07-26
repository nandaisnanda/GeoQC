"""Tests for the user-facing datum shift classification service."""

from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from geoqc.application.services import DatumShiftDetector
from geoqc.domain.models import (
    DatumShiftSample,
    DatumShiftStatus,
    DatumTransformationEvidence,
    GeographicBounds,
    TransformationQuality,
)

AREA = GeographicBounds(106.0, -7.0, 108.0, -5.0)


def evidence(
    shifts: tuple[float, ...],
    *,
    accuracy: float | None = 1.0,
    best: bool = True,
    ballpark: bool = False,
    missing_grids: tuple[str, ...] = (),
) -> DatumTransformationEvidence:
    samples = tuple(
        DatumShiftSample(106 + index, -6, 106 + index, -6, shift)
        for index, shift in enumerate(shifts)
    )
    return DatumTransformationEvidence(
        "EPSG:SOURCE",
        "EPSG:TARGET",
        "Test operation",
        accuracy,
        best,
        ballpark,
        missing_grids,
        samples,
    )


@dataclass
class FakeInspector:
    result: DatumTransformationEvidence
    received_points: Sequence[tuple[float, float]] = ()

    def inspect(
        self,
        source_crs: str,
        target_crs: str,
        area: GeographicBounds,
        sample_points: Sequence[tuple[float, float]],
    ) -> DatumTransformationEvidence:
        self.received_points = sample_points
        return self.result


def test_detector_reports_normal_shift_and_builds_complete_grid() -> None:
    inspector = FakeInspector(evidence((0.2, 0.4, 1.0)))

    result = DatumShiftDetector(inspector).detect(
        "EPSG:4326",
        "EPSG:3857",
        AREA,
        grid_size=3,
    )

    assert result.status is DatumShiftStatus.NORMAL
    assert result.quality is TransformationQuality.RELIABLE
    assert result.maximum_shift_m == 1.0
    assert result.mean_shift_m == pytest.approx(1.6 / 3)
    assert "normal" in result.summary
    assert "Tidak diperlukan" in result.recommendation
    assert len(inspector.received_points) == 9
    assert inspector.received_points[0] == (106.0, -7.0)
    assert inspector.received_points[-1] == (108.0, -5.0)


def test_detector_reports_abnormal_shift_in_plain_language() -> None:
    result = DatumShiftDetector(FakeInspector(evidence((2.0, 8.5)))).detect(
        "SOURCE",
        "TARGET",
        AREA,
        threshold_m=5.0,
    )

    assert result.status is DatumShiftStatus.ABNORMAL
    assert result.maximum_shift_m == 8.5
    assert len(result.abnormal_samples) == 1
    assert "tidak normal" in result.summary
    assert "jangan melakukan koreksi offset manual" in result.recommendation


def test_detector_warns_for_ballpark_missing_grid_and_poor_accuracy() -> None:
    result = DatumShiftDetector(
        FakeInspector(
            evidence(
                (1.0,),
                accuracy=10.0,
                best=False,
                ballpark=True,
                missing_grids=("regional_grid.tif",),
            )
        )
    ).detect("SOURCE", "TARGET", AREA, threshold_m=5.0)

    assert result.status is DatumShiftStatus.NORMAL
    assert result.quality is TransformationQuality.WARNING
    assert len(result.warnings) == 4
    assert any("ballpark" in warning for warning in result.warnings)
    assert any("regional_grid.tif" in warning for warning in result.warnings)
    assert any("10.00 m" in warning for warning in result.warnings)
    assert "grid PROJ" in result.recommendation


def test_detector_reports_unknown_accuracy_and_no_samples() -> None:
    result = DatumShiftDetector(FakeInspector(evidence((), accuracy=None))).detect(
        "SOURCE",
        "TARGET",
        AREA,
    )

    assert result.status is DatumShiftStatus.INDETERMINATE
    assert result.quality is TransformationQuality.WARNING
    assert result.maximum_shift_m is None
    assert "tidak dapat dinilai" in result.summary
    assert result.warnings == ("Akurasi operasi transformasi tidak diketahui.",)


@pytest.mark.parametrize(
    ("source", "target", "threshold", "grid_size", "message"),
    [
        ("", "TARGET", 5.0, 3, "must not be empty"),
        ("SOURCE", "TARGET", 0.0, 3, "greater than zero"),
        ("SOURCE", "TARGET", float("nan"), 3, "finite number"),
        ("SOURCE", "TARGET", 5.0, 1, "between 2 and 25"),
        ("SOURCE", "TARGET", 5.0, 26, "between 2 and 25"),
    ],
)
def test_detector_rejects_invalid_configuration(
    source: str,
    target: str,
    threshold: float,
    grid_size: int,
    message: str,
) -> None:
    detector = DatumShiftDetector(FakeInspector(evidence((1.0,))))

    with pytest.raises(ValueError, match=message):
        detector.detect(
            source,
            target,
            AREA,
            threshold_m=threshold,
            grid_size=grid_size,
        )


def test_detector_rejects_non_integer_grid_size() -> None:
    detector = DatumShiftDetector(FakeInspector(evidence((1.0,))))

    with pytest.raises(TypeError, match="must be an integer"):
        detector.detect("SOURCE", "TARGET", AREA, grid_size=True)
