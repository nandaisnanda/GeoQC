from __future__ import annotations

from collections import Counter

import geopandas as gpd  # type: ignore[import-untyped]
from shapely.geometry import LineString

from geoqc.domain.rules import Severity
from geoqc.infrastructure.gis.dataset_audit import audit_dataset, audit_geodataframe
from geoqc.infrastructure.gis.profile_loading import load_builtin_preset
from geoqc.interfaces.cli.main import _bind_preset_layer, _preset_profile


def _network() -> gpd.GeoDataFrame:
    lines = [
        LineString([(0, 0), (100, 0)]),  # 0: through road
        LineString([(100, 0), (200, 0)]),  # 1: through road
        LineString([(50, 0), (50, 60)]),  # 2: starts on the interior of feature 0
        LineString([(150, 40), (150, 1)]),  # 3: ends 1 m from feature 1
        LineString([(300, 300), (300, 400)]),  # 4: isolated
    ]
    return gpd.GeoDataFrame(geometry=lines, crs="EPSG:32749")


def _endpoint_issues() -> list:
    result = audit_geodataframe(
        _network(), dataset_name="jalan", profile=load_builtin_preset("jalan")
    )
    return [i for i in result.issues if i.code == "TOP-NO-DANGLES"]


def test_t_junction_and_undershoot_messages() -> None:
    issues = _endpoint_issues()

    t_junction = next(i for i in issues if i.title == "T-junction not noded")
    assert t_junction.feature_index == 2
    assert t_junction.message == "Feature 2 ends on feature 0 without a node."
    assert t_junction.metadata["other_feature"] == 0
    assert t_junction.severity is Severity.WARNING

    undershoot = next(i for i in issues if i.title == "Possible undershoot")
    assert undershoot.feature_index == 3
    assert undershoot.message == "Feature 3 ends 1.00 m from feature 1."
    assert undershoot.metadata["other_feature"] == 1
    assert undershoot.metadata["gap"] == 1.0
    assert undershoot.severity is Severity.WARNING

    assert not any("unconnected endpoint" in i.message for i in issues)


def test_jalanlokal_severity_counts_unchanged() -> None:
    profile = _bind_preset_layer(_preset_profile("jalan"), "jalan", "jalanlokal")

    result = audit_dataset("testdata/jalanlokal.shp", profile=profile)

    counts = Counter(
        issue.severity for issue in result.issues if issue.code == "TOP-NO-DANGLES"
    )
    assert counts[Severity.WARNING] == 178
    assert counts[Severity.INFO] == 130
