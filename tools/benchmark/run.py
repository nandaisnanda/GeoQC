"""Inject known defects into clean synthetic data, audit it, and report recall per defect type."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from inject import DEFECT_TYPES, Defect, inject, write_truth
from make_clean import build, write

import geoqc
from geoqc.domain.models import DatasetIssue, QualityProfile
from geoqc.infrastructure.gis.dataset_audit import audit_dataset
from geoqc.infrastructure.gis.profile_loading import _generic_profile, load_builtin_preset

HERE = Path(__file__).parent
ENDPOINT_CODES = frozenset({"ROAD-DEAD_END", "TOP-NO-DANGLES"})
CODE_TO_DEFECT = {
    "GEO-SELF_INTERSECTION": "self_intersection",
    "TOP-SLIVER": "sliver",
    "TOP-NO-OVERLAP": "overlap",
    "GEO-DUPLICATE_VERTEX": "duplicate_vertex",
}
# Road endpoint findings share one code; the audit names the case in the title.
ENDPOINT_TITLE_TO_DEFECT = {
    "Possible undershoot": "undershoot",
    "T-junction not noded": "unnoded_t_junction",
}


@dataclass(frozen=True)
class Row:
    defect_type: str
    layer: str
    injected: int
    found: int
    false_positives: int

    @property
    def recall(self) -> float:
        return self.found / self.injected if self.injected else 0.0


def defect_type_of(issue: DatasetIssue) -> str | None:
    """Map an audit finding to a benchmark defect type, or None if it maps to none."""
    if issue.code in ENDPOINT_CODES:
        return ENDPOINT_TITLE_TO_DEFECT.get(issue.title)
    return CODE_TO_DEFECT.get(issue.code)


def _features(issue: DatasetIssue) -> set[int]:
    return {
        index for index in (issue.feature_index, issue.related_feature_index) if index is not None
    }


def _profiles() -> dict[str, QualityProfile]:
    parcels = _generic_profile("Polygon")
    assert parcels is not None
    jalan = load_builtin_preset("jalan")
    # The preset's rules name a layer "jalan"; point them at the benchmark layer.
    rules = tuple(replace(rule, layer="roads") for rule in jalan.topology_rules)
    return {"parcels": parcels, "roads": replace(jalan, topology_rules=rules)}


def audit_layers(path: Path) -> dict[str, list[DatasetIssue]]:
    return {
        layer: list(audit_dataset(path, layer=layer, profile=profile).issues)
        for layer, profile in _profiles().items()
    }


def score(
    issues: dict[str, list[DatasetIssue]], defects: list[Defect]
) -> tuple[list[Row], Counter[tuple[str, str, str]]]:
    """Recall and false positives per defect type, plus a count of every other finding.

    A defect counts as found when a finding of its type names its feature or its
    related feature. A false positive is a finding of that type that names no feature
    carrying any injected defect. Other findings are keyed (layer, code, where).
    """
    touched = {
        layer: {
            index
            for item in defects
            if item.layer == layer
            for index in (item.feature_index, item.related_index)
            if index >= 0
        }
        for layer in issues
    }
    rows = []
    for defect_type in DEFECT_TYPES:
        expected = [item for item in defects if item.defect_type == defect_type]
        layer = expected[0].layer
        typed = [issue for issue in issues[layer] if defect_type_of(issue) == defect_type]
        named = set().union(*(_features(issue) for issue in typed))
        found = sum(1 for item in expected if {item.feature_index, item.related_index} & named)
        false_positives = sum(1 for issue in typed if not _features(issue) & touched[layer])
        rows.append(Row(defect_type, layer, len(expected), found, false_positives))
    other: Counter[tuple[str, str, str]] = Counter()
    for layer, layer_issues in issues.items():
        for issue in layer_issues:
            if defect_type_of(issue) is not None:
                continue
            features = _features(issue)
            where = (
                "no feature"
                if not features
                else "defect feature"
                if features & touched[layer]
                else "clean feature"
            )
            other[(layer, f"{issue.code} ({issue.title})", where)] += 1
    return rows, other


def commit_hash() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=HERE,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def render(
    rows: list[Row],
    other: Counter[tuple[str, str, str]],
    clean: Counter[tuple[str, str]],
    *,
    seed: int,
    parcels: int,
    per_type: int,
) -> str:
    lines = [
        "# GeoQC synthetic recall benchmark",
        "",
        f"geoqc {geoqc.__version__}, commit {commit_hash()}, seed {seed}, "
        f"{parcels} parcels, {per_type} defects per type.",
        "Profiles: generic-polygon for parcels, jalan for roads.",
        "",
        "| defect type | layer | injected | found | recall | false positives |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    lines += [
        f"| {row.defect_type} | {row.layer} | {row.injected} | {row.found} | "
        f"{row.recall:.0%} | {row.false_positives} |"
        for row in rows
    ]
    lines += [
        "",
        "False positives: findings of that type on features with no injected defect.",
        "",
        "## Other findings on the defect data",
        "",
        "| layer | finding | on | count |",
        "| --- | --- | --- | ---: |",
    ]
    lines += [
        f"| {layer} | {finding} | {where} | {count} |"
        for (layer, finding, where), count in sorted(other.items())
    ]
    lines += [
        "",
        "## Findings on the clean data (before injection)",
        "",
        "| layer | finding | count |",
        "| --- | --- | ---: |",
    ]
    lines += [
        f"| {layer} | {finding} | {count} |" for (layer, finding), count in sorted(clean.items())
    ]
    if not clean:
        lines.append("| - | none | 0 |")
    return "\n".join(lines) + "\n"


def benchmark(out: Path, *, parcels: int, road_cells: int, per_type: int, seed: int) -> str:
    """Build clean data, inject defects, audit both files, and return the markdown report."""
    clean_path, defect_path = out / "clean.gpkg", out / "defects.gpkg"
    parcel_frame, road_frame = build(parcels, road_cells)
    write(clean_path, parcel_frame, road_frame)
    parcel_defects, road_defects, defects = inject(parcel_frame, road_frame, per_type, seed)
    write(defect_path, parcel_defects, road_defects)
    write_truth(out / "truth.csv", defects)
    rows, other = score(audit_layers(defect_path), defects)
    clean = Counter(
        (layer, f"{issue.code} ({issue.title})")
        for layer, issues in audit_layers(clean_path).items()
        for issue in issues
    )
    return render(rows, other, clean, seed=seed, parcels=parcels, per_type=per_type)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parcels", type=int, default=400)
    parser.add_argument("--road-cells", type=int, default=10)
    parser.add_argument("--per-type", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=HERE / "out")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    options = {
        "parcels": args.parcels,
        "road_cells": args.road_cells,
        "per_type": args.per_type,
        "seed": args.seed,
    }
    # Run the whole pipeline twice from scratch: the two reports must match.
    first = benchmark(args.out, **options)
    print(first)
    second = benchmark(args.out, **options)
    print(second)
    (args.out / "results.md").write_text(first, encoding="utf-8")
    if first != second:
        sys.exit("Runs differ: the benchmark is not deterministic.")


if __name__ == "__main__":
    main()
