"""Tests for CRS audit value objects."""

import pytest

from geoqc.domain.models import (
    CrsAuditResult,
    CrsAuditStatus,
    CrsMetadata,
    DatasetCrsAudit,
    DatasetSource,
)


def test_dataset_source_builds_layer_identifier() -> None:
    source = DatasetSource("data.gpkg", layer="roads")

    assert source.identifier == "data.gpkg:roads"
    assert DatasetSource("roads.geojson").identifier == "roads.geojson"


def test_dataset_source_rejects_empty_uri() -> None:
    with pytest.raises(ValueError, match="URI"):
        DatasetSource("  ")


@pytest.mark.parametrize(
    ("canonical_wkt", "display_name"),
    [("", "EPSG:4326"), ("WKT", " ")],
)
def test_crs_metadata_rejects_incomplete_values(
    canonical_wkt: str,
    display_name: str,
) -> None:
    with pytest.raises(ValueError):
        CrsMetadata(canonical_wkt, display_name)


def test_audit_exposes_only_real_mismatches() -> None:
    source = DatasetSource("roads.gpkg")
    mismatch = DatasetCrsAudit(source, CrsAuditStatus.MISMATCH)
    missing = DatasetCrsAudit(source, CrsAuditStatus.MISSING)
    result = CrsAuditResult(None, (mismatch, missing))

    assert result.is_consistent is False
    assert result.mismatched_datasets == (mismatch,)


def test_empty_audit_is_not_consistent() -> None:
    assert CrsAuditResult(None, ()).is_consistent is False
