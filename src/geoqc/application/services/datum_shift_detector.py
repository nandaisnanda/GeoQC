"""Application service for detecting unusual datum shifts across an AOI."""

from math import isfinite
from statistics import fmean

from geoqc.application.ports import DatumTransformationInspector
from geoqc.domain.models import (
    DatumShiftAuditResult,
    DatumShiftStatus,
    DatumTransformationEvidence,
    GeographicBounds,
    TransformationQuality,
)


class DatumShiftDetector:
    """Classify measured shifts and transformation-operation quality."""

    def __init__(self, inspector: DatumTransformationInspector) -> None:
        self._inspector = inspector

    def detect(
        self,
        source_crs: str,
        target_crs: str,
        area: GeographicBounds,
        *,
        threshold_m: float = 5.0,
        grid_size: int = 3,
    ) -> DatumShiftAuditResult:
        """Evaluate a regular AOI grid and return a user-readable audit."""
        if not source_crs.strip() or not target_crs.strip():
            raise ValueError("Source and target CRS must not be empty")
        if not isfinite(threshold_m) or threshold_m <= 0:
            raise ValueError("Shift threshold must be a finite number greater than zero")
        if isinstance(grid_size, bool) or not isinstance(grid_size, int):
            raise TypeError("Grid size must be an integer")
        if not 2 <= grid_size <= 25:
            raise ValueError("Grid size must be between 2 and 25")

        evidence = self._inspector.inspect(
            source_crs,
            target_crs,
            area,
            self._grid(area, grid_size),
        )
        shifts = [sample.displacement_m for sample in evidence.samples]
        maximum = max(shifts, default=None)
        mean = fmean(shifts) if shifts else None
        status = self._status(maximum, threshold_m)
        warnings = self._warnings(evidence, threshold_m)
        quality = TransformationQuality.WARNING if warnings else TransformationQuality.RELIABLE
        return DatumShiftAuditResult(
            status=status,
            quality=quality,
            threshold_m=threshold_m,
            evidence=evidence,
            maximum_shift_m=maximum,
            mean_shift_m=mean,
            summary=self._summary(status, maximum, threshold_m, len(shifts)),
            warnings=warnings,
            recommendation=self._recommendation(status, quality),
        )

    @staticmethod
    def _grid(
        area: GeographicBounds,
        size: int,
    ) -> tuple[tuple[float, float], ...]:
        longitudes = (
            area.west + index * (area.east - area.west) / (size - 1) for index in range(size)
        )
        latitudes = tuple(
            area.south + index * (area.north - area.south) / (size - 1) for index in range(size)
        )
        return tuple((longitude, latitude) for longitude in longitudes for latitude in latitudes)

    @staticmethod
    def _status(maximum: float | None, threshold: float) -> DatumShiftStatus:
        if maximum is None:
            return DatumShiftStatus.INDETERMINATE
        if maximum > threshold:
            return DatumShiftStatus.ABNORMAL
        return DatumShiftStatus.NORMAL

    @staticmethod
    def _warnings(
        evidence: DatumTransformationEvidence,
        threshold: float,
    ) -> tuple[str, ...]:
        warnings: list[str] = []
        if not evidence.best_operation_available:
            warnings.append("Operasi transformasi terbaik tidak tersedia.")
        if evidence.uses_ballpark_transformation:
            warnings.append("PyProj menggunakan transformasi ballpark berakurasi rendah.")
        if evidence.missing_grids:
            grids = ", ".join(evidence.missing_grids)
            warnings.append(f"Grid transformasi yang dibutuhkan tidak tersedia: {grids}.")
        accuracy = evidence.declared_accuracy_m
        if accuracy is None:
            warnings.append("Akurasi operasi transformasi tidak diketahui.")
        elif accuracy > threshold:
            warnings.append(
                f"Akurasi deklaratif operasi ({accuracy:.2f} m) lebih buruk "
                f"dari ambang audit ({threshold:.2f} m)."
            )
        return tuple(warnings)

    @staticmethod
    def _summary(
        status: DatumShiftStatus,
        maximum: float | None,
        threshold: float,
        samples: int,
    ) -> str:
        if status is DatumShiftStatus.INDETERMINATE:
            return "Pergeseran datum tidak dapat dinilai karena tidak ada sampel valid."
        label = "tidak normal" if status is DatumShiftStatus.ABNORMAL else "normal"
        return (
            f"Pergeseran datum {label}: maksimum {maximum:.3f} m dari "
            f"{samples} sampel (ambang {threshold:.3f} m)."
        )

    @staticmethod
    def _recommendation(
        status: DatumShiftStatus,
        quality: TransformationQuality,
    ) -> str:
        if quality is TransformationQuality.WARNING:
            return (
                "Periksa ketersediaan grid PROJ dan pilih operasi transformasi resmi "
                "sebelum menggunakan hasil untuk keputusan produksi."
            )
        if status is DatumShiftStatus.ABNORMAL:
            return (
                "Verifikasi CRS sumber, datum target, dan riwayat transformasi data; "
                "jangan melakukan koreksi offset manual."
            )
        if status is DatumShiftStatus.INDETERMINATE:
            return "Periksa AOI dan definisi CRS, lalu jalankan audit kembali."
        return "Tidak diperlukan tindakan; simpan hasil audit sebagai bukti QC."
