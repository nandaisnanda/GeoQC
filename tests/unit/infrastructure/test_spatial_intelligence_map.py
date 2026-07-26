from pathlib import Path

from shapely.geometry import LineString, box

import geoqc
from geoqc.domain.models.spatial_intelligence import (
    BoundarySnapConfig,
    RoadNetworkConfig,
    SmallPolygonConfig,
)
from geoqc.infrastructure.reporting.spatial_intelligence_map import SpatialIntelligenceMap


def test_visualizer_writes_boundary_road_and_polygon_previews(tmp_path: Path) -> None:
    polygons = [box(0, 0, 1, 1), box(1.005, 0, 2.005, 1)]
    snap = geoqc.snap_boundaries(polygons, BoundarySnapConfig(tolerance=0.01))
    roads = [LineString([(0, 0), (0.5, 0)]), LineString([(0.505, 0), (2, 0)])]
    road_report = geoqc.analyze_road_network(roads, RoadNetworkConfig(connection_tolerance=0.01))
    small_report = geoqc.analyze_small_polygons(
        [box(0, 0, 10, 10), box(10, 0, 10.05, 2)],
        SmallPolygonConfig(
            sliver_area_threshold=0.2,
            sliver_compactness_threshold=0.1,
            noise_area_threshold=0.001,
            merge_tolerance=0.01,
        ),
    )
    renderer = SpatialIntelligenceMap()

    outputs = [
        renderer.boundary_snap(snap, tmp_path / "snap.html"),
        renderer.roads(road_report, [item.wkt for item in roads], tmp_path / "roads.html"),
        renderer.small_polygons(small_report, tmp_path / "small.html"),
    ]

    for output in outputs:
        assert output.exists()
        assert "leaflet" in output.read_text(encoding="utf-8").lower()
