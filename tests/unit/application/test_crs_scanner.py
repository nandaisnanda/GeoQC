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
    assert result.baseline == DatasetCrsMetadata(sources[1], WGS84)
    assert [item.source for item in result.datasets] == [sources[1], sources[0]]
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

    assert result.baseline == DatasetCrsMetadata(mismatch, WEB_MERCATOR)
    assert [item.status for item in result.datasets] == [
        CrsAuditStatus.CONSISTENT,
        CrsAuditStatus.MISSING,
        CrsAuditStatus.MISMATCH,
    ]
    assert [item.source for item in result.mismatched_datasets] == [baseline]
    assert "EPSG:4326" in (result.mismatched_datasets[0].message or "")


def test_scanner_result_does_not_depend_on_input_order() -> None:
    sources = [DatasetSource("z.gpkg"), DatasetSource("a.gpkg")]
    scanner = CrsConsistencyScanner(
        FakeReader({sources[0].identifier: WGS84, sources[1].identifier: WEB_MERCATOR})
    )

    assert scanner.scan(sources) == scanner.scan(reversed(sources))


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


def test_scanner_names_indonesian_crs_from_canonical_wkt() -> None:
    utm49s = CrsMetadata('PROJCRS["WGS 84 / UTM zone 49S",BASEGEOGCRS[]]', "EPSG:32749")
    sources = [DatasetSource("a.gpkg"), DatasetSource("b.gpkg")]
    scanner = CrsConsistencyScanner(FakeReader({"a.gpkg": WGS84, "b.gpkg": utm49s}))

    result = scanner.scan(sources)

    mismatch = result.datasets[1]
    assert mismatch.status is CrsAuditStatus.MISMATCH
    assert "Recognized Indonesian CRS: WGS 84 / UTM zone 49S" in (mismatch.message or "")
    assert result.datasets[0].message is None


def test_scanner_missing_crs_lists_indonesian_candidates_without_assigning() -> None:
    source = DatasetSource("no_prj.shp")
    result = CrsConsistencyScanner(FakeReader({source.identifier: None})).scan([source])

    missing = result.datasets[0]
    assert missing.status is CrsAuditStatus.MISSING
    assert missing.crs is None
    assert "SRGI2013" in (missing.message or "")
    assert "TM-3" in (missing.message or "")
