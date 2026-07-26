from shapely.geometry import LineString, box

from geoqc import (
    DatasetSnapshot,
    RepairCandidate,
    SpatialDuplicateConfig,
    SpatialLayer,
    analyze_spatial_conflicts,
    compare_datasets,
    detect_spatial_duplicates,
    prioritize_repairs,
)
from geoqc.domain.models.enterprise_spatial import ConflictType, DifferenceKind


def test_duplicate_detector_combines_metrics_and_reduces_candidates() -> None:
    report = detect_spatial_duplicates(
        [box(0, 0, 2, 2), box(0, 0, 2, 2), box(100, 100, 101, 101)],
        SpatialDuplicateConfig(similarity_threshold=0.9),
    )
    assert report.duplicate_count == 1
    assert report.pairs[0].similarity_percent == 100
    assert report.pairs[0].exact
    assert report.candidate_pairs < report.possible_pairs


def test_dataset_comparison_covers_schema_attribute_geometry_and_boundary() -> None:
    left = DatasetSnapshot(
        (box(0, 0, 1, 1).wkt,), ({"name": "old"},), "EPSG:3857", {"name": "str"}, "left"
    )
    right = DatasetSnapshot(
        (box(0, 0, 1.1, 1).wkt,),
        ({"name": "new", "code": 1},),
        "EPSG:3857",
        {"name": "str", "code": "int"},
        "right",
    )
    report = compare_datasets(left, right)
    assert report.count(DifferenceKind.MODIFIED) == 1
    assert report.schema_added == ("code",)
    assert report.boundary_iou < 1
    assert report.differences[0].changed_attributes == ("code", "name")


def test_conflict_analyzer_detects_building_in_river_and_road_crossing() -> None:
    report = analyze_spatial_conflicts(
        [
            SpatialLayer("roads", "road", (LineString([(-1, 0), (1, 0)]).wkt,)),
            SpatialLayer("river", "river", (box(-0.2, -1, 0.2, 1).wkt,)),
            SpatialLayer("buildings", "building", (box(-0.1, -0.1, 0.1, 0.1).wkt,)),
        ]
    )
    assert {item.conflict_type for item in report.conflicts} == {
        ConflictType.ROAD_RIVER_CROSSING,
        ConflictType.BUILDING_IN_RIVER,
    }
    assert report.conflicts[0].severity_score >= report.conflicts[1].severity_score


def test_repair_priority_is_deterministic_and_explainable() -> None:
    candidates = [
        RepairCandidate("b", "duplicate", 40, 30, 1, 2),
        RepairCandidate("a", "building_in_river", 95, 90, 10, 5),
    ]
    first = prioritize_repairs(candidates)
    second = prioritize_repairs(list(reversed(candidates)))
    assert first == second
    assert first[0].issue_id == "a"
    assert "deterministic weighted rule" in first[0].rationale


def test_line_duplicate_uses_length_based_iou() -> None:
    line = LineString([(0, 0), (1, 0)])
    report = detect_spatial_duplicates([line, LineString([(1, 0), (0, 0)])])
    assert report.pairs[0].iou == 1
