"""The Folium geometry helper shared by both spatial map renderers."""

import json
from pathlib import Path

from shapely.geometry import LineString, box, mapping

import geoqc
from geoqc.domain.models.spatial_intelligence import BoundarySnapConfig
from geoqc.infrastructure.reporting import enterprise_spatial_map, spatial_intelligence_map
from geoqc.infrastructure.reporting._folium_geometry import geojson_from_wkt, map_fitted_to
from geoqc.infrastructure.reporting.enterprise_spatial_map import EnterpriseSpatialMap
from geoqc.infrastructure.reporting.spatial_intelligence_map import SpatialIntelligenceMap


def _embedded_geometries(html: str) -> list[dict[str, object]]:
    """Parse every GeoJSON geometry Folium wrote into the page."""
    decoder = json.JSONDecoder()
    found: list[dict[str, object]] = []
    start = html.find('{"coordinates"')
    while start != -1:
        geometry, end = decoder.raw_decode(html, start)
        found.append(geometry)
        start = html.find('{"coordinates"', end)
    return found


def _as_json(value: object) -> object:
    """Round-trip through JSON so shapely tuples compare equal to parsed lists."""
    return json.loads(json.dumps(value))


def _html(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_geojson_from_wkt_matches_the_shapely_mapping() -> None:
    for geometry in (box(0, 0, 2, 1), LineString([(0, 0), (1, 1), (2, 0)])):
        assert geojson_from_wkt(geometry.wkt) == mapping(geometry)


def test_map_without_geometries_is_a_world_view() -> None:
    world = map_fitted_to([])

    assert world.location == [0, 0]
    assert 'class="folium-map"' in world.get_root().render()


def test_map_is_centred_on_the_union_extent_and_fitted_to_it() -> None:
    result = map_fitted_to([box(1, 2, 3, 5).wkt, box(7, 3, 11, 8).wkt])

    assert result.location == [5.0, 6.0]  # [mid latitude, mid longitude]
    assert "[[2.0, 1.0], [8.0, 11.0]]" in result.get_root().render()


def test_scale_bar_is_added_only_when_requested() -> None:
    wkts = [box(0, 0, 1, 1).wkt]

    assert "L.control.scale" not in map_fitted_to(wkts).get_root().render()
    assert "L.control.scale" in map_fitted_to(wkts, control_scale=True).get_root().render()


def test_renderers_no_longer_carry_their_own_copies() -> None:
    for module in (enterprise_spatial_map, spatial_intelligence_map):
        assert not hasattr(module, "_geojson")
        assert not hasattr(module, "_map")


def test_enterprise_map_embeds_both_duplicates_with_a_scale_bar(tmp_path: Path) -> None:
    report = geoqc.detect_spatial_duplicates(
        [box(0, 0, 1, 1), box(0, 0, 1, 1)], geoqc.SpatialDuplicateConfig(similarity_threshold=0.9)
    )

    html = _html(EnterpriseSpatialMap().duplicates(report, tmp_path / "duplicates.html"))

    geometries = _embedded_geometries(html)
    assert geometries == [_as_json(mapping(box(0, 0, 1, 1)))] * 2
    assert "Duplicate left" in html
    assert "Duplicate right" in html
    assert "L.control.scale" in html


def test_spatial_intelligence_map_embeds_before_and_after_without_a_scale_bar(
    tmp_path: Path,
) -> None:
    polygons = [box(0, 0, 1, 1), box(1.005, 0, 2.005, 1)]
    report = geoqc.snap_boundaries(polygons, BoundarySnapConfig(tolerance=0.01))

    html = _html(SpatialIntelligenceMap().boundary_snap(report, tmp_path / "snap.html"))

    geometries = _embedded_geometries(html)
    assert len(geometries) == 2 * len(report.features)
    assert geometries[0] == _as_json(geojson_from_wkt(report.features[0].before_wkt))
    assert geometries[1] == _as_json(geojson_from_wkt(report.features[0].after_wkt))
    assert "Before" in html
    assert "After" in html
    assert "L.control.scale" not in html
