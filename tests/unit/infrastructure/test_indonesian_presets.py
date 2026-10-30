from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import pytest
from shapely import box

import geoqc

EXAMPLES = Path(__file__).resolve().parents[3] / "docs" / "examples"
PRESETS = (
    "batas-administrasi",
    "bidang-tanah",
    "kawasan-hutan",
    "jalan",
    "konsesi-kawasan-hutan",
)


@pytest.mark.parametrize("name", PRESETS)
def test_indonesian_preset_loads_without_attribute_rules(name: str) -> None:
    profile = geoqc.load_quality_profile(EXAMPLES / f"{name}.yaml")

    assert profile.name == name
    assert profile.attribute_rules == ()
    assert profile.id_column is None
    assert profile.topology_rules


def test_concession_overlapping_kawasan_hutan_is_flagged() -> None:
    profile = geoqc.load_quality_profile(EXAMPLES / "konsesi-kawasan-hutan.yaml")
    frames = {
        "konsesi": gpd.GeoDataFrame(
            geometry=[
                box(500_000, 9_200_000, 501_000, 9_201_000),
                box(510_000, 9_200_000, 511_000, 9_201_000),
            ],
            crs="EPSG:32748",
        ),
        "kawasan_hutan": gpd.GeoDataFrame(
            geometry=[box(500_500, 9_200_500, 502_000, 9_202_000)],
            crs="EPSG:32748",
        ),
    }

    result = geoqc.audit_layers(frames, profile=profile)

    hits = [issue for issue in result.issues if issue.issue_type == "must_not_intersect"]
    assert [(issue.layer, issue.feature_index) for issue in hits] == [("konsesi", 0)]
