from __future__ import annotations

import math
import sys
from pathlib import Path
from types import ModuleType

import pytest
from shapely import union_all
from shapely.geometry import Polygon, box

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
