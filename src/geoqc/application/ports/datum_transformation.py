"""Port for inspecting location-aware datum transformations."""

from collections.abc import Sequence
from typing import Protocol

from geoqc.domain.models import (
    DatumTransformationEvidence,
    GeographicBounds,
)


class DatumTransformationInspector(Protocol):
    """Inspect one CRS transformation and measure shifts at sample coordinates."""

    def inspect(
        self,
        source_crs: str,
        target_crs: str,
        area: GeographicBounds,
        sample_points: Sequence[tuple[float, float]],
    ) -> DatumTransformationEvidence:
        """Return operation metadata and horizontal displacement evidence."""
        ...
