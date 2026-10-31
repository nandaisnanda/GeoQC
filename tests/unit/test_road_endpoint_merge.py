from __future__ import annotations

from collections import Counter
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
from shapely.geometry import LineString
from typer.testing import CliRunner

from geoqc.domain.models import DatasetAuditResult
from geoqc.domain.rules import Severity
from geoqc.infrastructure.gis.dataset_audit import audit_geodataframe
from geoqc.infrastructure.gis.profile_loading import load_builtin_preset
from geoqc.interfaces.cli.main import app


def _network() -> gpd.GeoDataFrame:
    """3x3 grid (12 edges) + 3 undershoots, 2 cul-de-sacs and 1 spur."""
    lines = []
    for row in range(3):
        for col in range(2):
            lines.append(LineString([(col * 100, row * 100), ((col + 1) * 100, row * 100)]))
            lines.append(LineString([(row * 100, col * 100), (row * 100, (col + 1) * 100)]))
    # Undershoots: end 1 m short of the y=200 road, far end is a plain road end.
    lines += [LineString([(x, 300), (x, 201)]) for x in (20, 50, 80)]
    # Cul-de-sacs leaving grid nodes.
    lines += [LineString([(100, 0), (100, -80)]), LineString([(200, 100), (280, 100)])]
    # Spur: 5 m stub on a grid node.
    lines.append(LineString([(100, 200), (100, 205)]))
    return gpd.GeoDataFrame(geometry=lines, crs="EPSG:32749")


def _audit() -> tuple[Counter[tuple[str, Severity]], DatasetAuditResult]:
    profile = load_builtin_preset("jalan")
    result = audit_geodataframe(_network(), dataset_name="jalan", profile=profile)
    return Counter((issue.code, issue.severity) for issue in result.issues), result


def test_endpoints_are_reported_once_and_graded() -> None:
    counts, result = _audit()

    assert counts[("TOP-NO-DANGLES", Severity.WARNING)] == 3
    assert counts[("TOP-NO-DANGLES", Severity.INFO)] == 6
    assert not any(code == "ROAD-DEAD_END" for code, _ in counts)
    merged = [i for i in result.issues if i.code == "TOP-NO-DANGLES"]
    assert all(i.metadata["rule_codes"] == "TOP-NO-DANGLES,ROAD-DEAD_END" for i in merged)
    assert not any(code == "ROAD-UNNODED_INTERSECTION" for code, _ in counts)


def test_road_ends_do_not_count_as_errors_in_cli(tmp_path: Path) -> None:
    source = tmp_path / "net.gpkg"
    _network().to_file(source, layer="jalan", driver="GPKG")

    result = CliRunner().invoke(
        app, ["check", str(source), "--layer", "jalan", "--preset", "jalan", "--no-output"]
    )

    # Three stubs plus the one road they undershoot; the 6 road ends are info only.
    assert "4 of 18 features have errors" in result.stdout, result.stdout
<<<<<<< HEAD


def test_road_ends_alone_pass_the_quality_gate() -> None:
    network = _network()
    only_ends = gpd.GeoDataFrame(
        geometry=[*network.geometry[:12], *network.geometry[15:17]], crs=network.crs
    )
    profile = load_builtin_preset("jalan")

    result = audit_geodataframe(only_ends, dataset_name="jalan", profile=profile)

    assert {issue.severity for issue in result.issues} == {Severity.INFO}
    assert result.passes(profile.gate)
=======
>>>>>>> 9839fa00722e6c810dd2f8affaf06f52c3c746ed
