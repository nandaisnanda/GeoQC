"""Unit tests for the Arrow-WKB streaming geometry processor."""

import pyarrow as pa  # type: ignore[import-untyped]
import pytest
from shapely.geometry import Point

from geoqc.application.streaming.models import DatasetMetadata, FeatureChunk
from geoqc.infrastructure.gis.shapely_geometry_validator import ShapelyGeometryValidator
from geoqc.infrastructure.gis.streaming.geometry_processor import GeometryChunkProcessor

UNCLOSED_RING = bytes.fromhex(
    "01030000000100000003000000"
    "00000000000000000000000000000000"
    "000000000000f03f0000000000000000"
    "000000000000f03f000000000000f03f"
)
ONE_POINT_LINE = bytes.fromhex("01020000000100000000000000000000000000000000000000")


@pytest.mark.parametrize("payload", [UNCLOSED_RING, ONE_POINT_LINE])
def test_unparseable_wkb_is_reported_as_invalid_geometry(payload: bytes) -> None:
    batch = pa.record_batch({"geometry": pa.array([Point(0, 0).wkb, payload], type=pa.binary())})
    metadata = DatasetMetadata("Parquet", None, None, 2, "geometry")

    result = GeometryChunkProcessor(ShapelyGeometryValidator()).process(
        FeatureChunk(10, batch, 2), metadata
    )

    assert result.feature_count == 2
    assert result.invalid_feature_count == 1
    assert result.issue_counts == {"invalid_geometry": 1}
    finding = result.findings[0]
    assert finding.feature_index == 11
    assert finding.issues[0][1].startswith("WKB could not be parsed: ")
