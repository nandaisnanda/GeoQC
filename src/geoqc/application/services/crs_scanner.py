"""Application service that audits CRS consistency across datasets."""

from collections.abc import Iterable

from geoqc.application.ports import CrsMetadataReader
from geoqc.domain.exceptions import DatasetMetadataReadError
from geoqc.domain.models import (
    CrsAuditResult,
    CrsAuditStatus,
    DatasetCrsAudit,
    DatasetCrsMetadata,
    DatasetSource,
)


class CrsConsistencyScanner:
    """Compare normalized CRS metadata using the first valid CRS as baseline."""

    def __init__(self, reader: CrsMetadataReader) -> None:
        self._reader = reader

    def scan(self, sources: Iterable[DatasetSource]) -> CrsAuditResult:
        """Read every source and return a complete audit without failing fast."""
        metadata: list[DatasetCrsMetadata | DatasetCrsAudit] = []
        for source in sources:
            try:
                metadata.append(self._reader.read(source))
            except DatasetMetadataReadError as error:
                metadata.append(
                    DatasetCrsAudit(
                        source=source,
                        status=CrsAuditStatus.ERROR,
                        message=error.reason,
                    )
                )

        baseline = next(
            (
                item
                for item in metadata
                if isinstance(item, DatasetCrsMetadata) and item.crs is not None
            ),
            None,
        )
        datasets = tuple(self._classify(item, baseline) for item in metadata)
        return CrsAuditResult(baseline=baseline, datasets=datasets)

    @staticmethod
    def _classify(
        item: DatasetCrsMetadata | DatasetCrsAudit,
        baseline: DatasetCrsMetadata | None,
    ) -> DatasetCrsAudit:
        if isinstance(item, DatasetCrsAudit):
            return item
        if item.crs is None:
            return DatasetCrsAudit(
                source=item.source,
                status=CrsAuditStatus.MISSING,
                message="Dataset does not declare a CRS.",
            )
        if baseline is None or baseline.crs is None:
            return DatasetCrsAudit(
                source=item.source,
                status=CrsAuditStatus.ERROR,
                crs=item.crs,
                message="No valid baseline CRS is available.",
            )
        status = (
            CrsAuditStatus.CONSISTENT
            if item.crs.canonical_wkt == baseline.crs.canonical_wkt
            else CrsAuditStatus.MISMATCH
        )
        message = None
        if status is CrsAuditStatus.MISMATCH:
            message = (
                f"CRS {item.crs.display_name!r} differs from baseline "
                f"{baseline.crs.display_name!r}."
            )
        return DatasetCrsAudit(source=item.source, status=status, crs=item.crs, message=message)
