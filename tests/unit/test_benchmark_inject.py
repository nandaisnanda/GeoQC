from __future__ import annotations

import math
import sys
from pathlib import Path
from types import ModuleType

import geopandas as gpd  # type: ignore[import-untyped]
import pytest
from shapely import union_all
from shapely.geometry import Point, Polygon, box

BENCHMARK = Path(__file__).parents[2] / "tools" / "benchmark"


@pytest.fixture
def bench(monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, ModuleType]:
    # inject.py and make_clean.py import each other by bare name.
    monkeypatch.syspath_prepend(str(BENCHMARK))
    for name in ("inject", "make_clean"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    import inject  # type: ignore[import-not-found]
    import make_clean  # type: ignore[import-not-found]

    return inject, make_clean


def test_sites_never_touch_across_types(bench: tuple[ModuleType, ModuleType]) -> None:
    inject, make_clean = bench
    parcels, roads = make_clean.build(900, 10)
    layers = {"parcels": list(parcels.geometry), "roads": list(roads.geometry)}

    sites = inject.plan(layers["parcels"], layers["roads"], 4, seed=3)

    for layer, geometries in layers.items():
        groups = [
            set(features)
            for defect_type, found in sites.items()
            if inject.LAYER_OF[defect_type] == layer
            for features, _ in found
        ]
        for i, left in enumerate(groups):
            for right in groups[i + 1 :]:
                assert not any(geometries[a].intersects(geometries[b]) for a in left for b in right)


def test_plan_reports_the_layer_that_ran_out(bench: tuple[ModuleType, ModuleType]) -> None:
    inject, make_clean = bench
    parcels, roads = make_clean.build(16, 10)

    with pytest.raises(inject.NotEnoughSites) as error:
        inject.plan(list(parcels.geometry), list(roads.geometry), 4, seed=3)

    assert error.value.layer == "parcels"


def test_sliver_tolerance_is_the_compactness_threshold(
    bench: tuple[ModuleType, ModuleType],
) -> None:
    inject, _ = bench
    width = inject.sliver_tolerance(20.0)
    strip = box(0, 0, 20, width)

    assert 4 * math.pi * strip.area / strip.length**2 == pytest.approx(0.05)


@pytest.mark.parametrize(
    ("ratio", "expected"), [(0.5, True), (0.9, True), (1.1, False), (2, False)]
)
def test_undershoot_magnitude_follows_the_ratio(
    bench: tuple[ModuleType, ModuleType], ratio: float, expected: bool
) -> None:
    inject, make_clean = bench
    parcels, roads = make_clean.build(1600, 6)
    lines = list(roads.geometry)
    sites = inject.plan(list(parcels.geometry), lines, 2, seed=1)

    ((_, magnitude),) = inject.magnitudes("undershoot", [ratio])
    tolerance = inject.SPECS["undershoot"].tolerance

    shortened, defects = inject.apply(
        "undershoot", sites["undershoot"], lines, magnitude, tolerance
    )

    for defect in defects:
        index = defect.feature_index
        assert defect.magnitude == pytest.approx(ratio * 2.0)
        assert lines[index].length - shortened[index].length == pytest.approx(defect.magnitude)
        assert defect.ratio_r == pytest.approx(ratio)
        assert defect.expected_detect is expected


def test_t_junction_keeps_every_feature_and_unnodes_the_stem(
    bench: tuple[ModuleType, ModuleType],
) -> None:
    inject, make_clean = bench
    parcels, roads = make_clean.build(1600, 6)
    lines = list(roads.geometry)
    sites = inject.plan(list(parcels.geometry), lines, 2, seed=1)

    out, defects = inject.apply(
        "unnoded_t_junction", sites["unnoded_t_junction"], lines, None, None
    )

    assert len(out) == len(lines)
    for defect in defects:
        stem, through = out[defect.feature_index], out[defect.related_index]
        assert stem.distance(through) < 1e-9
        assert stem.distance(through.boundary) > 0.5


def _parcel_sites(
    bench: tuple[ModuleType, ModuleType], per_type: int = 3
) -> tuple[list[object], dict[str, list[object]]]:
    inject, make_clean = bench
    parcels, roads = make_clean.build(1600, 6)
    geometries = list(parcels.geometry)
    return geometries, inject.plan(geometries, list(roads.geometry), per_type, seed=5)


@pytest.mark.parametrize("ratio", [0.5, 0.9, 1.1, 2, 10])
def test_gap_leaves_an_enclosed_hole_of_ratio_times_tolerance(
    bench: tuple[ModuleType, ModuleType], ratio: float
) -> None:
    inject, _ = bench
    geometries, sites = _parcel_sites(bench)
    ((_, magnitude),) = inject.magnitudes("gap", [ratio])

    out, defects = inject.apply("gap", sites["gap"], geometries, magnitude, 1.0)

    holes = [
        Polygon(ring)
        for part in getattr(union_all(out), "geoms", [union_all(out)])
        for ring in part.interiors
    ]
    assert len(holes) == len(defects)
    for defect in defects:
        pair = union_all([out[defect.feature_index], out[defect.related_index]])
        (hole,) = [item for item in holes if item.intersects(pair)]
        assert hole.area == pytest.approx(ratio * 1.0, rel=1e-6)
        assert defect.expected_detect is (ratio <= 1)


def test_duplicate_exact_appends_an_equal_copy(bench: tuple[ModuleType, ModuleType]) -> None:
    inject, _ = bench
    geometries, sites = _parcel_sites(bench)
    spec = inject.SPECS["duplicate_exact"]

    out, defects = inject.apply(
        "duplicate_exact", sites["duplicate_exact"], geometries, spec.magnitude, spec.tolerance
    )

    assert len(out) == len(geometries) + len(defects)
    for defect in defects:
        assert out[defect.feature_index].equals(out[defect.related_index])
        assert defect.expected_detect is True


def test_duplicate_jitter_moves_every_vertex_by_delta(
    bench: tuple[ModuleType, ModuleType],
) -> None:
    inject, _ = bench
    geometries, sites = _parcel_sites(bench)
    spec = inject.SPECS["duplicate_jitter"]

    out, defects = inject.apply(
        "duplicate_jitter",
        sites["duplicate_jitter"],
        geometries,
        spec.magnitude,
        spec.tolerance,
        seed=5,
    )

    for defect in defects:
        original, copy = out[defect.feature_index], out[defect.related_index]
        assert copy.hausdorff_distance(original) <= spec.magnitude * 1.01
        assert not copy.equals(original)
        assert copy.is_valid
        assert defect.expected_detect is False


@pytest.mark.parametrize("ratio", [0.5, 0.9, 1.1, 2, 10])
def test_minimum_area_shrinks_to_ratio_times_tolerance(
    bench: tuple[ModuleType, ModuleType], ratio: float
) -> None:
    inject, make_clean = bench
    geometries, sites = _parcel_sites(bench)
    ((_, magnitude),) = inject.magnitudes("minimum_area", [ratio])

    out, defects = inject.apply("minimum_area", sites["minimum_area"], geometries, magnitude, 10.0)

    assert make_clean.CRS == "EPSG:32748"
    for defect in defects:
        shrunk, before = out[defect.feature_index], geometries[defect.feature_index]
        assert shrunk.area == pytest.approx(ratio * 10.0, rel=1e-9)
        assert before.contains(shrunk)
        assert defect.expected_detect is (ratio < 1)


def test_empty_and_null_geometries_survive_a_gpkg_round_trip(
    bench: tuple[ModuleType, ModuleType], tmp_path: Path
) -> None:
    inject, make_clean = bench
    geometries, sites = _parcel_sites(bench)

    for defect_type, check in (
        ("empty_polygon", lambda frame, i: frame.geometry.iloc[i].is_empty),
        ("null_geometry", lambda frame, i: frame.geometry.isna().iloc[i]),
    ):
        out, defects = inject.apply(defect_type, sites[defect_type], geometries, None, None)
        path = tmp_path / f"{defect_type}.gpkg"
        gpd.GeoDataFrame(geometry=out, crs=make_clean.CRS).to_file(path, layer="parcels")
        frame = gpd.read_file(path, layer="parcels")

        assert len(frame) == len(geometries)
        for defect in defects:
            assert check(frame, defect.feature_index)
            assert defect.expected_detect is True
        untouched = set(range(len(geometries))) - {item.feature_index for item in defects}
        assert not frame.geometry.isna().iloc[sorted(untouched)].any()


@pytest.mark.parametrize("ratio", [0.5, 0.9, 1.1, 2])
def test_spike_apex_angle_is_ratio_times_minimum_angle(
    bench: tuple[ModuleType, ModuleType], ratio: float
) -> None:
    inject, _ = bench
    geometries, sites = _parcel_sites(bench)
    ((_, magnitude),) = inject.magnitudes("spike", [ratio])

    out, defects = inject.apply("spike", sites["spike"], geometries, magnitude, 10.0)

    for defect in defects:
        spiked, before = out[defect.feature_index], geometries[defect.feature_index]
        (apex,) = [
            point for point in spiked.exterior.coords[:-1] if not before.covers(Point(point))
        ]
        ring = list(spiked.exterior.coords[:-1])
        at = ring.index(apex)
        (ax, ay), (bx, by) = ring[at - 1], ring[(at + 1) % len(ring)]
        first, second = (ax - apex[0], ay - apex[1]), (bx - apex[0], by - apex[1])
        angle = math.atan2(
            abs(first[0] * second[1] - first[1] * second[0]),
            first[0] * second[0] + first[1] * second[1],
        )
        assert angle == pytest.approx(math.radians(ratio * 10.0), abs=1e-6)
        assert spiked.is_valid
        assert geometries[defect.related_index].contains(Point(apex))
        assert defect.expected_detect is (ratio < 1)


def test_spike_sweep_stops_at_ratio_two(bench: tuple[ModuleType, ModuleType]) -> None:
    inject, _ = bench

    assert [ratio for ratio, _ in inject.magnitudes("spike", [0.5, 2, 10])] == [0.5, 2]


@pytest.mark.parametrize("ratio", [0.5, 0.9, 1.1, 2, 10])
def test_min_vertex_distance_adds_an_adjacent_vertex_at_ratio_times_tolerance(
    bench: tuple[ModuleType, ModuleType], ratio: float
) -> None:
    inject, _ = bench
    geometries, sites = _parcel_sites(bench)
    ((_, magnitude),) = inject.magnitudes("min_vertex_distance", [ratio])

    out, defects = inject.apply(
        "min_vertex_distance", sites["min_vertex_distance"], geometries, magnitude, 0.05
    )

    for defect in defects:
        edited, before = out[defect.feature_index], geometries[defect.feature_index]
        ring = list(edited.exterior.coords)
        closest = min(math.dist(a, b) for a, b in zip(ring, ring[1:], strict=False))
        # The injector records the spacing as placed; floats near x = 430,000 hold the
        # nominal ratio x 0.05 to within 6e-11 m.
        assert closest == pytest.approx(defect.magnitude, abs=1e-12)
        assert defect.magnitude == pytest.approx(ratio * 0.05, abs=1e-9)
        assert len(ring) == len(before.exterior.coords) + 1
        assert edited.area == pytest.approx(before.area, abs=1e-9)
        assert edited.equals(before)
        assert all(
            abs(value / 0.001 - round(value / 0.001)) < 1e-6 for point in ring for value in point
        )
        assert defect.expected_detect is (ratio < 1)


def test_precision_grid_moves_exactly_one_vertex_off_the_grid(
    bench: tuple[ModuleType, ModuleType],
) -> None:
    inject, _ = bench
    geometries, sites = _parcel_sites(bench)
    spec = inject.SPECS["precision_grid"]

    def deviation(point: tuple[float, float]) -> float:
        return math.hypot(*(value - round(value / 0.001) * 0.001 for value in point))

    out, defects = inject.apply(
        "precision_grid", sites["precision_grid"], geometries, spec.magnitude, spec.tolerance
    )

    for defect in defects:
        ring = list(out[defect.feature_index].exterior.coords)[:-1]
        off = [point for point in ring if deviation(point) > 1e-9]
        assert len(off) == 1
        assert deviation(off[0]) == pytest.approx(0.0003, abs=1e-9)
        assert all(deviation(point) <= 1e-9 for point in ring if point != off[0])
        assert out[defect.feature_index].is_valid
        assert defect.expected_detect is True


@pytest.mark.parametrize("ratio", [0.5, 0.9, 1.1, 2, 10])
def test_overshoot_extends_the_stem_past_the_through_road(
    bench: tuple[ModuleType, ModuleType], ratio: float
) -> None:
    inject, make_clean = bench
    parcels, roads = make_clean.build(1600, 6)
    lines = list(roads.geometry)
    sites = inject.plan(list(parcels.geometry), lines, 2, seed=1)
    ((_, magnitude),) = inject.magnitudes("overshoot", [ratio])

    out, defects = inject.apply("overshoot", sites["overshoot"], lines, magnitude, 2.0)

    assert len(out) == len(lines)
    for defect in defects:
        stem, through = out[defect.feature_index], out[defect.related_index]
        crossing = stem.intersection(through)
        assert crossing.geom_type == "Point"
        # Along the stem, the crossing lies s short of the nearer (moved) end.
        along = stem.project(crossing)
        assert min(along, stem.length - along) == pytest.approx(ratio * 2.0, abs=1e-9)
        assert stem.length - lines[defect.feature_index].length == pytest.approx(
            ratio * 2.0, abs=1e-9
        )
        assert crossing.distance(stem.boundary) == pytest.approx(ratio * 2.0, abs=1e-9)
        assert defect.expected_detect is (ratio < 1)


def test_duplicate_segments_copy_the_road_fully_or_in_part(
    bench: tuple[ModuleType, ModuleType],
) -> None:
    inject, make_clean = bench
    parcels, roads = make_clean.build(1600, 6)
    lines = list(roads.geometry)
    sites = inject.plan(list(parcels.geometry), lines, 2, seed=1)

    for defect_type in ("duplicate_segment_full", "duplicate_segment_partial"):
        spec = inject.SPECS[defect_type]
        out, defects = inject.apply(
            defect_type, sites[defect_type], lines, spec.magnitude, spec.tolerance
        )

        assert len(out) == len(lines) + len(defects)
        for defect in defects:
            road, copy = out[defect.feature_index], out[defect.related_index]
            assert road.intersection(copy).length / copy.length >= 0.99
            assert copy.length / road.length == pytest.approx(spec.magnitude)
            if defect_type == "duplicate_segment_full":
                assert copy.equals(road)
            else:
                assert not copy.equals(road)
                assert road.covers(copy)
            assert defect.expected_detect is True
