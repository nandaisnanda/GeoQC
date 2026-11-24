"""Application service that audits CRS consistency across datasets."""

import re
from collections.abc import Iterable

from geoqc.application.ports import CrsMetadataReader
from geoqc.domain.exceptions import DatasetMetadataReadError
from geoqc.domain.models import (
    CrsAuditResult,
    CrsAuditStatus,
    DatasetCrsAudit,
    DatasetCrsMetadata,
    DatasetIssue,
    DatasetSource,
    IssueGeometryKind,
    RepairRisk,
)
from geoqc.domain.rules import Severity

CRS_LAYER_MISMATCH = "CRS-LAYER-MISMATCH"

_INDONESIAN_CRS_NAME = re.compile(r"^(SRGI2013|DGN95)|^WGS 84 / UTM zone (4[6-9]|5[0-4])S$")
_WKT_NAME = re.compile(r'^[A-Z0-9_]+\[\s*"([^"]+)"')


class CrsConsistencyScanner:
    """Compare normalized CRS metadata using the first valid CRS as baseline."""

    def __init__(self, reader: CrsMetadataReader) -> None:
        self._reader = reader

    def scan(self, sources: Iterable[DatasetSource]) -> CrsAuditResult:
        """Read every source and return a complete audit without failing fast."""
        ordered_sources = sorted(
            sources,
            key=lambda source: (source.uri.casefold(), (source.layer or "").casefold()),
        )
        metadata: list[DatasetCrsMetadata | DatasetCrsAudit] = []
        for source in ordered_sources:
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
                message=(
                    "Dataset does not declare a CRS. For Indonesian data check SRGI2013, "
                    "DGN95, WGS 84 / UTM zone 46S-54S or DGN95 / Indonesia TM-3; the "
                    "audit suggests one from the coordinates. No CRS was assigned."
                ),
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
        message = _indonesian_label(item.crs.canonical_wkt)
        if status is CrsAuditStatus.MISMATCH:
            message = (
                f"CRS {item.crs.display_name!r} differs from baseline "
                f"{baseline.crs.display_name!r}.{message}"
            )
        return DatasetCrsAudit(
            source=item.source, status=status, crs=item.crs, message=message or None
        )


def _indonesian_label(canonical_wkt: str) -> str:
    match = _WKT_NAME.match(canonical_wkt.strip())
    if match is None or not _INDONESIAN_CRS_NAME.search(match.group(1)):
        return ""
    return f" Recognized Indonesian CRS: {match.group(1)}."


def layer_crs_mismatch_issues(
    sources: Iterable[DatasetSource], reader: CrsMetadataReader
) -> dict[str, DatasetIssue]:
    """Return one CRS-LAYER-MISMATCH warning per layer whose CRS differs from the baseline.

    Reuses CrsConsistencyScanner, so the baseline is the first valid CRS in sorted
    order. Layers without a CRS are not mismatches; the missing-CRS check reports them.
    Nothing is reprojected and no CRS is assigned.
    """
    audit = CrsConsistencyScanner(reader).scan(sources)
    baseline = audit.baseline
    if baseline is None or baseline.crs is None:
        return {}
    issues: dict[str, DatasetIssue] = {}
    for item in audit.mismatched_datasets:
        layer = item.source.layer
        if layer is None or item.crs is None:
            continue
        baseline_layer = baseline.source.layer or baseline.source.identifier
        issues[layer] = DatasetIssue(
            code=CRS_LAYER_MISMATCH,
            issue_type="layer_crs_mismatch",
            title="Layer CRS mismatch",
            message=(
                f"Layer {layer!r} uses {item.crs.display_name} but layer {baseline_layer!r} "
                f"uses {baseline.crs.display_name}. No layer was reprojected and no CRS was "
                "assigned."
            ),
            severity=Severity.WARNING,
            category="metadata",
            recommendation=(
                "Confirm which CRS is correct, then reproject the other layers yourself "
                "before overlaying or combining them."
            ),
            repair_risk=RepairRisk.NOT_REPAIRABLE,
            geometry_kind=IssueGeometryKind.POINT,
            geometry_wkt="POINT EMPTY",
            layer=layer,
            metadata={
                "layer_crs": item.crs.display_name,
                "baseline_layer": baseline_layer,
                "baseline_crs": baseline.crs.display_name,
            },
        )
    return issues
