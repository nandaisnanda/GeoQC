import pytest
import shapely
from shapely.geometry import LineString, MultiLineString, box
from shapely.geometry.base import BaseGeometry

from geoqc.domain.models.spatial_intelligence import (
    BoundarySnapConfig,
    Recommendation,
    RoadIssueType,
    RoadNetworkConfig,
    RoadNetworkRepairConfig,
    SmallPolygonConfig,
    SmallPolygonIssueType,
)
from geoqc.infrastructure.gis.shapely_spatial_intelligence import (
    ShapelyBoundarySnapper,
    ShapelyRoadNetworkAnalyzer,
    ShapelyRoadNetworkRepairer,
    ShapelySmallPolygonAnalyzer,
)

SpatialEngine = (
    ShapelyBoundarySnapper
    | ShapelyRoadNetworkAnalyzer
    | ShapelyRoadNetworkRepairer
    | ShapelySmallPolygonAnalyzer
)


def _wkt(geometry: BaseGeometry) -> str:
    return str(shapely.to_wkt(geometry, rounding_precision=-1))


def test_boundary_snap_closes_small_gap_without_overlap_and_reports_area() -> None:
    polygons = [box(0, 0, 1, 1), box(1.005, 0, 2.005, 1)]

    result = ShapelyBoundarySnapper().snap(
        [_wkt(item) for item in polygons],
        BoundarySnapConfig(tolerance=0.01, max_relative_area_change=0.01),
    )

    repaired = [shapely.from_wkt(item.after_wkt) for item in result.features]
    assert result.candidate_pairs == 1
    assert result.repaired == 1
    assert repaired[0].distance(repaired[1]) == pytest.approx(0)
    assert repaired[0].intersection(repaired[1]).area == pytest.approx(0)
    assert result.total_area_delta == pytest.approx(0.005)
    assert result.features[1].area_after - result.features[1].area_before == pytest.approx(0.005)


def test_boundary_snap_rejects_excessive_area_change() -> None:
    polygons = [box(0, 0, 1, 1), box(1.005, 0, 2.005, 1)]

    result = ShapelyBoundarySnapper().snap(
        [_wkt(item) for item in polygons],
        BoundarySnapConfig(tolerance=0.01, max_relative_area_change=0.001),
    )

    assert result.repaired == 0
    assert result.total_area_delta == pytest.approx(0)
    assert "area change" in result.features[1].reason


def test_road_analyzer_detects_every_requested_issue_and_builds_report() -> None:
    roads = [
        LineString([(0, 0), (0.5, 0)]),
        LineString([(0.505, 0), (2, 0)]),
        LineString([(3, 0), (3.2, 0)]),
        LineString([(3, 0), (3.2, 0)]),
        LineString([(5, 0), (5.1, 0), (5.1, 0.1), (5, 0.1), (5, 0)]),
        LineString([(7, 0), (9, 0)]),
        LineString([(8, -1), (8, 1)]),
    ]

    report = ShapelyRoadNetworkAnalyzer().analyze(
        [_wkt(item) for item in roads],
        RoadNetworkConfig(
            connection_tolerance=0.01,
            dangling_length_threshold=0.6,
            max_loop_length=1,
        ),
    )

    detected = {finding.issue_type for finding in report.findings}
    assert detected == set(RoadIssueType)
    assert report.feature_count == len(roads)
    assert report.issue_counts["duplicate_segment"] == 1
    assert report.to_dict()["findings"]


def test_road_analyzer_checks_every_multiline_part() -> None:
    roads = [
        MultiLineString(
            [
                [(0, 0), (10, 0)],
                [(20, 0), (20.1, 0)],
            ]
        )
    ]

    report = ShapelyRoadNetworkAnalyzer().analyze(
        [_wkt(item) for item in roads],
        RoadNetworkConfig(dangling_length_threshold=1),
    )

    dangling = [item for item in report.findings if item.issue_type is RoadIssueType.DANGLING_ROAD]
    assert len(dangling) == 2
    assert all(item.feature_indices == (0,) for item in dangling)


def test_road_repair_snaps_gap_nodes_crossing_and_preserves_provenance() -> None:
    roads = [
        LineString([(0, 0), (2, 0)]),
        LineString([(1, -1), (1, 1)]),
        LineString([(2.05, 0), (3, 0)]),
    ]

    result = ShapelyRoadNetworkRepairer().repair(
        [_wkt(item) for item in roads],
        RoadNetworkRepairConfig(snap_tolerance=0.1),
    )

    repaired = [shapely.from_wkt(item.geometry_wkt) for item in result.segments]
    assert result.snapped_endpoint_count == 1
    assert result.output_segment_count == 5
    assert all(item.source_indices for item in result.segments)
    assert all(item.is_simple and item.is_valid for item in repaired)
    assert shapely.union_all(repaired).length == pytest.approx(5)
    assert result.to_dict()["output_segment_count"] == 5


def test_road_repair_endpoint_cluster_never_exceeds_snap_tolerance() -> None:
    roads = [
        LineString([(-2, -2), (0, 0)]),
        LineString([(0.09, -2), (0.09, 0)]),
        LineString([(2.18, -2), (0.18, 0)]),
    ]

    result = ShapelyRoadNetworkRepairer().repair(
        [_wkt(item) for item in roads], RoadNetworkRepairConfig(snap_tolerance=0.1)
    )
    repaired = shapely.union_all([shapely.from_wkt(item.geometry_wkt) for item in result.segments])

    assert result.snapped_endpoint_count == 2
    assert repaired.intersects(shapely.Point(0.09, 0))
    assert all(
        shapely.Point(line.coords[-1]).distance(shapely.Point(0.09, 0)) <= 0.1 for line in roads
    )


def test_small_polygon_analyzer_classifies_and_previews_recommendations() -> None:
    polygons = [
        box(0, 0, 10, 10),
        box(10, 0, 10.05, 2),
        box(20, 20, 20.2, 20.2),
        box(30, 30, 30.01, 30.01),
    ]
    config = SmallPolygonConfig(
        sliver_area_threshold=0.2,
        sliver_compactness_threshold=0.1,
        tiny_island_area_threshold=0.05,
        isolation_distance=5,
        noise_area_threshold=0.001,
        merge_tolerance=0.01,
        max_target_area_change=0.01,
    )

    report = ShapelySmallPolygonAnalyzer().analyze([_wkt(item) for item in polygons], config)
    by_type = {item.issue_type: item for item in report.findings}

    assert set(by_type) == set(SmallPolygonIssueType)
    assert by_type[SmallPolygonIssueType.SLIVER_POLYGON].recommendation == Recommendation.MERGE
    assert by_type[SmallPolygonIssueType.SLIVER_POLYGON].preview_wkt is not None
    assert by_type[SmallPolygonIssueType.TINY_ISLAND].recommendation == Recommendation.DELETE
    assert by_type[SmallPolygonIssueType.NOISE_GEOMETRY].recommendation == Recommendation.DELETE


@pytest.mark.parametrize(
    ("engine", "wkt"),
    [
        (ShapelyBoundarySnapper(), "LINESTRING (0 0, 1 1)"),
        (ShapelyRoadNetworkAnalyzer(), "POLYGON ((0 0, 1 0, 1 1, 0 0))"),
        (ShapelyRoadNetworkRepairer(), "POLYGON ((0 0, 1 0, 1 1, 0 0))"),
        (ShapelySmallPolygonAnalyzer(), "LINESTRING (0 0, 1 1)"),
    ],
)
def test_engines_reject_wrong_geometry_family(engine: SpatialEngine, wkt: str) -> None:
    with pytest.raises(ValueError):
        if isinstance(engine, ShapelyBoundarySnapper):
            engine.snap([wkt], BoundarySnapConfig())
        elif isinstance(engine, ShapelyRoadNetworkAnalyzer):
            engine.analyze([wkt], RoadNetworkConfig())
        elif isinstance(engine, ShapelyRoadNetworkRepairer):
            engine.repair([wkt], RoadNetworkRepairConfig())
        else:
            assert isinstance(engine, ShapelySmallPolygonAnalyzer)
            engine.analyze([wkt], SmallPolygonConfig())
