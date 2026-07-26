"""Tests for the CRS consistency scanner application service."""

from dataclasses import dataclass

from geoqc.application.services import CrsConsistencyScanner
from geoqc.domain.exceptions import DatasetMetadataReadError
from geoqc.domain.models import (
    CrsAuditStatus,
    CrsMetadata,
    DatasetCrsMetadata,
    DatasetSource,
)

WGS84 = CrsMetadata("canonical-wgs84", "EPSG:4326", "EPSG:4326")
WEB_MERCATOR = CrsMetadata("canonical-web-mercator", "EPSG:3857", "EPSG:3857")


@dataclass
class FakeReader:
    """Deterministic metadata reader used by scanner tests."""

    values: dict[str, CrsMetadata | None | Exception]

    def read(self, source: DatasetSource) -> DatasetCrsMetadata:
        value = self.values[source.identifier]
        if isinstance(value, Exception):
            raise value
        return DatasetCrsMetadata(source, value)


def test_scanner_reports_consistent_datasets() -> None:
    sources = [DatasetSource("roads.gpkg"), DatasetSource("buildings.gpkg")]
    scanner = CrsConsistencyScanner(FakeReader({source.identifier: WGS84 for source in sources}))

    result = scanner.scan(sources)

    assert result.is_consistent is True
    assert result.baseline == DatasetCrsMetadata(sources[0], WGS84)
    assert [item.status for item in result.datasets] == [
        CrsAuditStatus.CONSISTENT,
        CrsAuditStatus.CONSISTENT,
    ]


def test_scanner_identifies_different_crs_against_first_valid_baseline() -> None:
    missing = DatasetSource("missing.geojson")
    baseline = DatasetSource("roads.gpkg")
    mismatch = DatasetSource("buildings.gpkg")
    scanner = CrsConsistencyScanner(
        FakeReader(
            {
                missing.identifier: None,
                baseline.identifier: WGS84,
                mismatch.identifier: WEB_MERCATOR,
            }
        )
    )

    result = scanner.scan([missing, baseline, mismatch])

    assert result.baseline == DatasetCrsMetadata(baseline, WGS84)
    assert [item.status for item in result.datasets] == [
        CrsAuditStatus.MISSING,
        CrsAuditStatus.CONSISTENT,
        CrsAuditStatus.MISMATCH,
    ]
    assert [item.source for item in result.mismatched_datasets] == [mismatch]
    assert "EPSG:3857" in (result.mismatched_datasets[0].message or "")


def test_scanner_keeps_read_error_in_audit_and_continues() -> None:
    broken = DatasetSource("broken.gpkg")
    valid = DatasetSource("roads.gpkg")
    scanner = CrsConsistencyScanner(
        FakeReader(
            {
                broken.identifier: DatasetMetadataReadError(broken.identifier, "not readable"),
                valid.identifier: WGS84,
            }
        )
    )

    result = scanner.scan([broken, valid])

    assert result.datasets[0].status is CrsAuditStatus.ERROR
    assert result.datasets[0].message == "not readable"
    assert result.datasets[1].status is CrsAuditStatus.CONSISTENT


def test_scanner_reports_missing_when_no_dataset_declares_crs() -> None:
    source = DatasetSource("unknown.geojson")

    result = CrsConsistencyScanner(FakeReader({source.identifier: None})).scan([source])

    assert result.baseline is None
    assert result.datasets[0].status is CrsAuditStatus.MISSING
    assert result.is_consistent is False
