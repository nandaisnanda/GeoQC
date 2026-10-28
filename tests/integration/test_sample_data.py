"""The README quick-start sample must keep reporting its known defects."""

from pathlib import Path

import geoqc

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "examples" / "sample_defects.gpkg"
PROFILES = ROOT / "docs" / "examples"


def test_sample_parcels_report_known_defects() -> None:
    result = geoqc.audit_dataset(SAMPLE, layer="parcels", profile=PROFILES / "parcel-profile.yaml")

    found = {(issue.code, issue.feature_index) for issue in result.issues}
    assert ("GEO-SELF_INTERSECTION", 1) in found
    assert ("TOP-MINIMUM-AREA", 2) in found
    assert ("TOP-NO-OVERLAP", 0) in found


def test_sample_roads_report_disconnected_segment() -> None:
    result = geoqc.audit_dataset(
        SAMPLE, layer="roads", profile=PROFILES / "road-network-profile.yaml"
    )

    dead_ends = {i.feature_index for i in result.issues if i.code == "ROAD-DEAD_END"}
    assert dead_ends == {1, 3}
