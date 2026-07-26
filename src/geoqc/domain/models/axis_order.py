"""Value objects for geographic axis-order validation."""

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from geoqc.domain.models.datum_shift import GeographicBounds


@dataclass(frozen=True, slots=True)
class CoordinateBounds:
    """Observed bounding box whose axes have not yet been trusted."""

    minimum_x: float
    minimum_y: float
    maximum_x: float
    maximum_y: float

    def __post_init__(self) -> None:
        values = (self.minimum_x, self.minimum_y, self.maximum_x, self.maximum_y)
        if not all(isfinite(value) for value in values):
            raise ValueError("Coordinate bounds must be finite numbers")
        if self.minimum_x >= self.maximum_x or self.minimum_y >= self.maximum_y:
            raise ValueError("Coordinate bounds must have positive width and height")


class AxisOrderStatus(StrEnum):
    """Classification of an observed geographic bounding box."""

    CORRECT = "correct"
    LIKELY_SWAPPED = "likely_swapped"
    AMBIGUOUS = "ambiguous"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class AxisOrderAuditResult:
    """Evidence and guidance produced by an axis-order audit."""

    status: AxisOrderStatus
    observed_bounds: CoordinateBounds
    expected_bounds: GeographicBounds | None
    declared_bounds: GeographicBounds | None
    swapped_bounds: GeographicBounds | None
    declared_spatial_match: bool | None
    swapped_spatial_match: bool | None
    summary: str
    recommendation: str

    @property
    def axes_likely_swapped(self) -> bool:
        """Return whether evidence uniquely supports the swapped interpretation."""
        return self.status is AxisOrderStatus.LIKELY_SWAPPED
