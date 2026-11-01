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
    assert len(truth) == 12
    keys = [(row["layer"], row["feature_index"]) for row in truth]
    assert len(set(keys)) == len(keys)
