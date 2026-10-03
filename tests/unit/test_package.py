"""Tests for the initial package contract."""

import pytest
from shapely import box, from_wkt
from shapely.geometry import LineString, Polygon

import geoqc


def test_package_exposes_version() -> None:
    """The installable package must expose its typed version metadata."""
    assert geoqc.__version__ == "0.1.0"


def test_package_exposes_geometry_validation_api() -> None:
    """Users can validate geometry without importing internal adapters."""
    geometry = Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])

    result = geoqc.validate_geometry(geometry)

    assert not result.is_valid
    assert result.has_issue(geoqc.GeometryIssueType.SELF_INTERSECTION)


def test_repair_geometry_makes_a_bowtie_valid() -> None:
    """The top-level repair API fixes a self-intersecting polygon."""
    result = geoqc.repair_geometry(Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]))

    assert result.is_changed
    assert from_wkt(result.after_wkt).is_valid


def test_repair_geometry_rejects_non_geometry() -> None:
    """Passing a non-geometry is a contract error detected early."""
    with pytest.raises(TypeError):
        geoqc.repair_geometry(object())  # type: ignore[arg-type]


def test_repair_geometries_resolves_overlap() -> None:
    """The coverage API erases overlap from the later feature."""
    coverage = geoqc.repair_geometries([box(0, 0, 2, 2), box(1, 0, 3, 2)])

    assert coverage.report.action_counts.get("overlap") == 1


def test_open_repair_session_supports_preview_apply_undo() -> None:
    """The session exposes preview, apply, and undo over the same engine."""
    session = geoqc.open_repair_session([Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])])

    assert session.preview().repaired_count == 1
    before = session.geometries
    session.apply()
    assert session.geometries != before
    session.undo()
    assert session.geometries == before


def test_open_repair_session_rejects_non_geometry() -> None:
    """Session construction validates every input geometry."""
    with pytest.raises(TypeError):
        geoqc.open_repair_session([object()])  # type: ignore[list-item]


def test_public_road_repair_returns_noded_segments() -> None:
    """The public repair API snaps small gaps and nodes line crossings."""
    roads = [
        LineString([(0, 0), (2, 0)]),
        LineString([(1, -1), (1, 1)]),
        LineString([(2.05, 0), (3, 0)]),
    ]

    result = geoqc.repair_road_network(roads, geoqc.RoadNetworkRepairConfig(snap_tolerance=0.1))

    assert result.snapped_endpoint_count == 1
    assert result.output_segment_count == 5
