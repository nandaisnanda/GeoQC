from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

BENCHMARK = Path(__file__).parents[2] / "tools" / "benchmark"


def _load(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    # run.py imports its sibling scripts by bare name.
    monkeypatch.syspath_prepend(str(BENCHMARK))
    spec = importlib.util.spec_from_file_location("benchmark_run", BENCHMARK / "run.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Its dataclasses look themselves up in sys.modules.
    monkeypatch.setitem(sys.modules, "benchmark_run", module)
    spec.loader.exec_module(module)
    return module


def test_small_benchmark_finds_every_bowtie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _load(monkeypatch)

    report = run.benchmark(tmp_path, parcels=40, road_cells=4, per_type=2, seed=7)

    assert "| self_intersection | parcels | 2 | 2 | 100% |" in report
    with (tmp_path / "truth.csv").open(encoding="utf-8") as handle:
        truth = list(csv.DictReader(handle))
    # One truth row per injected defect: per_type for every defect type.
    assert len(truth) == 2 * len(run.DEFECT_TYPES)
    keys = [(row["layer"], row["feature_index"]) for row in truth]
    assert len(set(keys)) == len(keys)


def test_report_counts_overshoot_ends_titled_as_undershoots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _load(monkeypatch)

    report = run.benchmark(tmp_path, parcels=40, road_cells=4, per_type=2, seed=7)

    # At r = 0.5 the end lies 1 m past the through road, inside the 2 m merge radius.
    assert (
        "contradictory titles (EPSG:32748): 2/2 overshoot ends also titled "
        "'Possible undershoot' (r=0.5: 2/2)" in report
    )
