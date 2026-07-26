"""Value objects for location-aware datum shift audits."""

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


@dataclass(frozen=True, slots=True)
class GeographicBounds:
    """Non-antimeridian geographic area of interest in longitude/latitude."""

    west: float
    south: float
    east: float
    north: float

    def __post_init__(self) -> None:
        values = (self.west, self.south, self.east, self.north)
        if not all(isfinite(value) for value in values):
            raise ValueError("AOI bounds must be finite numbers")
        if not (-180 <= self.west < self.east <= 180):
            raise ValueError("AOI must satisfy -180 <= west < east <= 180")
        if not (-90 <= self.south < self.north <= 90):
            raise ValueError("AOI must satisfy -90 <= south < north <= 90")


@dataclass(frozen=True, slots=True)
class DatumShiftSample:
    """Observed horizontal coordinate shift at one geographic sample point."""

    longitude: float
    latitude: float
    transformed_longitude: float
    transformed_latitude: float
    displacement_m: float


@dataclass(frozen=True, slots=True)
class DatumTransformationEvidence:
    """PyProj-independent evidence returned by a transformation inspector."""

    source_crs: str
    target_crs: str
    operation_name: str
    declared_accuracy_m: float | None
    best_operation_available: bool
    uses_ballpark_transformation: bool
    missing_grids: tuple[str, ...]
    samples: tuple[DatumShiftSample, ...]


class DatumShiftStatus(StrEnum):
    """User-facing classification of observed datum displacement."""

    NORMAL = "normal"
    ABNORMAL = "abnormal"
    INDETERMINATE = "indeterminate"


class TransformationQuality(StrEnum):
    """Confidence classification for the selected coordinate operation."""

    RELIABLE = "reliable"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class DatumShiftAuditResult:
    """Complete datum-shift audit with concise user guidance."""

    status: DatumShiftStatus
    quality: TransformationQuality
    threshold_m: float
    evidence: DatumTransformationEvidence
    maximum_shift_m: float | None
    mean_shift_m: float | None
    summary: str
    warnings: tuple[str, ...]
    recommendation: str

    @property
    def abnormal_samples(self) -> tuple[DatumShiftSample, ...]:
        """Return samples whose displacement exceeds the configured threshold."""
        return tuple(
            sample for sample in self.evidence.samples if sample.displacement_m > self.threshold_m
        )
