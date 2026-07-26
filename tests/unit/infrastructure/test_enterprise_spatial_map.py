from pathlib import Path

from shapely.geometry import LineString, box

from geoqc import (
    DatasetSnapshot,
    SpatialDuplicateConfig,
    SpatialLayer,
    analyze_spatial_conflicts,
    compare_datasets,
    detect_spatial_duplicates,
)
from geoqc.domain.models.enterprise_spatial import SpatialDuplicateReport
from geoqc.infrastructure.reporting.enterprise_spatial_map import EnterpriseSpatialMap


def _html(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_duplicate_map_contains_similarity_layers_and_supports_empty_reports(
    tmp_path: Path,
) -> None:
    renderer = EnterpriseSpatialMap()
    report = detect_spatial_duplicates(
        [box(0, 0, 1, 1), box(0, 0, 1, 1)],
        SpatialDuplicateConfig(similarity_threshold=0.9),
    )

    populated = renderer.duplicates(report, tmp_path / "nested" / "duplicates.html")
    empty = renderer.duplicates(
        SpatialDuplicateReport(0, 0, 0, 0, ()), tmp_path / "empty.html"
    )

    assert populated.exists()
    assert "100.00% similar" in _html(populated)
    assert "Duplicate left" in _html(populated)
    assert "L.control.layers" in _html(empty)


def test_difference_map_renders_before_after_and_change_classification(tmp_path: Path) -> None:
    report = compare_datasets(
        DatasetSnapshot(
            (box(0, 0, 1, 1).wkt, box(5, 5, 6, 6).wkt),
            ({"name": "old"}, {"name": "removed"}),
            name="before",
        ),
        DatasetSnapshot(
            (box(0, 0, 1.1, 1).wkt, box(10, 10, 11, 11).wkt),
            ({"name": "new"}, {"name": "added"}),
            name="after",
        ),
    )

    path = EnterpriseSpatialMap().differences(report, tmp_path / "differences.html")
    html = _html(path)

    assert "modified" in html
    assert "removed" in html
    assert "added" in html
    assert "before" in html and "after" in html


def test_conflict_map_renders_severity_and_conflict_type(tmp_path: Path) -> None:
    report = analyze_spatial_conflicts(
        [
            SpatialLayer("roads", "road", (LineString([(-1, 0), (1, 0)]).wkt,)),
            SpatialLayer("river", "river", (box(-0.2, -1, 0.2, 1).wkt,)),
            SpatialLayer("buildings", "building", (box(-0.1, -0.1, 0.1, 0.1).wkt,)),
        ]
    )

    path = EnterpriseSpatialMap().conflicts(report, tmp_path / "conflicts.html")
    html = _html(path)

    assert "building_in_river" in html
    assert "road_river_crossing" in html
    assert "Severity" in html