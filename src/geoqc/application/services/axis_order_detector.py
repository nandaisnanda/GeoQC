"""Application service for detecting swapped longitude and latitude axes."""

from geoqc.domain.models import (
    AxisOrderAuditResult,
    AxisOrderStatus,
    CoordinateBounds,
    GeographicBounds,
)


class AxisOrderDetector:
    """Compare declared and swapped interpretations of a geographic bbox."""

    def detect(
        self,
        observed: CoordinateBounds,
        *,
        expected: GeographicBounds | None = None,
    ) -> AxisOrderAuditResult:
        """Classify axis order using coordinate ranges and optional spatial context."""
        declared = self._geographic_bounds(
            observed.minimum_x,
            observed.minimum_y,
            observed.maximum_x,
            observed.maximum_y,
        )
        swapped = self._geographic_bounds(
            observed.minimum_y,
            observed.minimum_x,
            observed.maximum_y,
            observed.maximum_x,
        )
        declared_match = self._spatial_match(declared, expected)
        swapped_match = self._spatial_match(swapped, expected)
        status = self._classify(
            declared is not None,
            swapped is not None,
            declared_match,
            swapped_match,
            expected is not None,
        )
        return AxisOrderAuditResult(
            status=status,
            observed_bounds=observed,
            expected_bounds=expected,
            declared_bounds=declared,
            swapped_bounds=swapped,
            declared_spatial_match=declared_match,
            swapped_spatial_match=swapped_match,
            summary=self._summary(status, expected is not None),
            recommendation=self._recommendation(status),
        )

    @staticmethod
    def _geographic_bounds(
        west: float,
        south: float,
        east: float,
        north: float,
    ) -> GeographicBounds | None:
        try:
            return GeographicBounds(west, south, east, north)
        except ValueError:
            return None

    @staticmethod
    def _spatial_match(
        candidate: GeographicBounds | None,
        expected: GeographicBounds | None,
    ) -> bool | None:
        if expected is None:
            return None
        if candidate is None:
            return False
        return max(candidate.west, expected.west) < min(candidate.east, expected.east) and max(
            candidate.south, expected.south
        ) < min(candidate.north, expected.north)

    @staticmethod
    def _classify(
        declared_valid: bool,
        swapped_valid: bool,
        declared_match: bool | None,
        swapped_match: bool | None,
        has_expected: bool,
    ) -> AxisOrderStatus:
        if has_expected:
            if declared_match and not swapped_match:
                return AxisOrderStatus.CORRECT
            if swapped_match and not declared_match:
                return AxisOrderStatus.LIKELY_SWAPPED
            if declared_match and swapped_match:
                return AxisOrderStatus.AMBIGUOUS
            return AxisOrderStatus.INVALID
        if declared_valid and not swapped_valid:
            return AxisOrderStatus.CORRECT
        if swapped_valid and not declared_valid:
            return AxisOrderStatus.LIKELY_SWAPPED
        if declared_valid and swapped_valid:
            return AxisOrderStatus.AMBIGUOUS
        return AxisOrderStatus.INVALID

    @staticmethod
    def _summary(status: AxisOrderStatus, has_expected: bool) -> str:
        context = " dan expected bounds" if has_expected else ""
        messages = {
            AxisOrderStatus.CORRECT: (
                f"Urutan axis longitude/latitude konsisten dengan rentang koordinat{context}."
            ),
            AxisOrderStatus.LIKELY_SWAPPED: (
                f"Latitude dan longitude kemungkinan tertukar berdasarkan bounding box{context}."
            ),
            AxisOrderStatus.AMBIGUOUS: (
                "Kedua urutan axis sama-sama valid; bounding box belum cukup untuk memastikan."
            ),
            AxisOrderStatus.INVALID: (
                "Bounding box tidak valid secara geografis atau tidak cocok "
                "dengan area yang diharapkan."
            ),
        }
        return messages[status]

    @staticmethod
    def _recommendation(status: AxisOrderStatus) -> str:
        if status is AxisOrderStatus.LIKELY_SWAPPED:
            return (
                "Verifikasi metadata CRS dan mapping field, lalu tukar axis pada tahap ingest; "
                "jangan mengubah data sumber tanpa bukti."
            )
        if status is AxisOrderStatus.AMBIGUOUS:
            return "Berikan expected geographic bounds atau validasi dengan feature referensi."
        if status is AxisOrderStatus.INVALID:
            return "Periksa CRS, unit koordinat, nilai bbox, dan area cakupan dataset."
        return "Urutan axis dapat dipertahankan; simpan hasil audit sebagai bukti QC."
