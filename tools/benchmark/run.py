"""Inject known defects into clean synthetic data, audit it, and report recall per defect type.

Sweep: for each seed, plan isolated defect sites once (in metres), then for each target
CRS and each ratio write one file per defect type, reproject it, audit it, and score it.
"""

from __future__ import annotations

import argparse
import csv
import math
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import numpy as np
import shapely
from inject import (
    DEFAULT_RATIO,
    DEFECT_TYPES,
    LAYER_OF,
    SWEPT,
    Defect,
    NotEnoughSites,
    Site,
    apply,
    plan,
    truth_record,
    write_truth,
)
from make_clean import CRS as BASE_CRS
from make_clean import build
from pyproj import Transformer
from scoring import Finding, classify, match, subtract_baseline, wilson
from shapely.geometry.base import BaseGeometry

import geoqc
from geoqc.domain.models import (
    CheckStatus,
    DatasetAuditResult,
    DatasetIssue,
    QualityProfile,
    TopologyRule,
    TopologyRuleType,
)
from geoqc.domain.rules import Severity
from geoqc.infrastructure.gis.dataset_audit import audit_dataset
from geoqc.infrastructure.gis.dataset_checks import _metric_skip_reason
from geoqc.infrastructure.gis.profile_loading import _generic_profile, load_builtin_preset

HERE = Path(__file__).parent
# Each defect type is scored under exactly one profile.
PROFILE_OF = {
    "self_intersection": "generic-polygon",
    "sliver": "generic-polygon",
    "overlap": "generic-polygon",
    "duplicate_vertex": "generic-polygon",
    "undershoot": "jalan",
    "unnoded_t_junction": "jalan",
}
# Findings the clean data is expected to carry: (layer, code, title).
EXPECTED_CLEAN = frozenset(
    {
        # The four cul-de-sacs end with no other road nearby.
        ("roads", "TOP-NO-DANGLES", "Road end"),
        # jalan requires a projected CRS: in EPSG:4326 this is how the user sees the guard.
        ("roads", "META-GEOGRAPHIC_CRS", "Geographic Crs"),
    }
)
ENDPOINT_CODES = frozenset({"ROAD-DEAD_END", "TOP-NO-DANGLES"})
CODE_TO_DEFECT = {
    "GEO-SELF_INTERSECTION": "self_intersection",
    "TOP-SLIVER": "sliver",
    "TOP-NO-OVERLAP": "overlap",
    "GEO-DUPLICATE_VERTEX": "duplicate_vertex",
    "TOP-NO-OVERSHOOT-UNDERSHOOT": "overshoot",
}
# Road endpoint findings share one code; the audit names the case in the title.
ENDPOINT_TITLE_TO_DEFECT = {
    "Possible undershoot": "undershoot",
    "T-junction not noded": "unnoded_t_junction",
}
# The code(s) whose findings score each defect type, for recall.csv.
RULE_CODES = {
    **{defect_type: (code,) for code, defect_type in CODE_TO_DEFECT.items()},
    "undershoot": ("TOP-NO-DANGLES", "ROAD-DEAD_END"),
    # ROAD-DEAD_END cannot fire here: the stem's end touches the through line.
    "unnoded_t_junction": ("TOP-NO-DANGLES",),
}
CSV_COLUMNS = (
    "defect_type",
    "profile",
    "rule_code",
    "crs",
    "ratio_r",
    "expected_detect",
    "seed",
    "injected",
    "found",
    "recall",
    "wilson_low",
    "wilson_high",
    "fp_clean",
    "fp_clean_unexpected",
    "fp_defects",
    "collateral",
    "guard_skipped",
    "guard_reported",
)
GUARD_CARRIER = "checks[topology].status=skipped"
QUICK_PER_TYPE, QUICK_SEEDS, QUICK_RATIOS = 20, 1, (0.5, 2.0)


def _bench_parcels() -> QualityProfile:
    """Explicit parcel profile for the rules generic-polygon does not run."""

    def rule(rule_type: TopologyRuleType, **thresholds: float) -> TopologyRule:
        return TopologyRule(rule_type, "parcels", severity=Severity.WARNING, **thresholds)

    return QualityProfile(
        name="bench-parcels",
        require_crs=False,
        enabled_checks=("geometry", "crs", "topology"),
        expected_geometry_types=("Polygon", "MultiPolygon"),
        topology_rules=(
            rule(TopologyRuleType.NO_GAP, tolerance=1.0),
            rule(TopologyRuleType.MINIMUM_AREA, minimum_area=10.0),
            rule(TopologyRuleType.NO_SPIKES, minimum_angle=10.0),
            rule(TopologyRuleType.MINIMUM_VERTEX_DISTANCE, minimum_distance=0.05),
            rule(TopologyRuleType.PRECISION_GRID, precision_grid_size=0.001, tolerance=1e-9),
        ),
    )


def profiles() -> dict[str, tuple[str, QualityProfile]]:
    """Profile name -> (layer, profile)."""
    generic = _generic_profile("Polygon")
    assert generic is not None
    jalan = load_builtin_preset("jalan")
    # The preset's rules name a layer "jalan"; point them at the benchmark layer.
    rules = tuple(replace(rule, layer="roads") for rule in jalan.topology_rules)
    return {
        "generic-polygon": ("parcels", generic),
        "bench-parcels": ("parcels", _bench_parcels()),
        "jalan": ("roads", replace(jalan, topology_rules=rules)),
    }


@dataclass(frozen=True)
class Row:
    defect_type: str
    profile: str
    layer: str
    crs: str
    ratio_r: float | None
    expected_detect: bool
    seed: int
    injected: int
    found: int
    fp_clean: int
    fp_clean_unexpected: int
    fp_defects: int
    collateral: int
    guard_skipped: bool
    guard_reported: bool

    @property
    def recall(self) -> float | None:
        if self.guard_skipped:
            return None
        return self.found / self.injected if self.injected else 0.0

    @property
    def interval(self) -> tuple[float, float] | None:
        return None if self.guard_skipped else wilson(self.found, self.injected)

    def csv_record(self) -> dict[str, object]:
        recall, interval = self.recall, self.interval
        return {
            "defect_type": self.defect_type,
            "profile": self.profile,
            "rule_code": "|".join(RULE_CODES[self.defect_type]),
            "crs": self.crs,
            "ratio_r": "" if self.ratio_r is None else f"{self.ratio_r:g}",
            "expected_detect": self.expected_detect,
            "seed": self.seed,
            "injected": self.injected,
            "found": self.found,
            "recall": "" if recall is None else f"{recall:.4f}",
            "wilson_low": "" if interval is None else f"{interval[0]:.4f}",
            "wilson_high": "" if interval is None else f"{interval[1]:.4f}",
            "fp_clean": self.fp_clean,
            "fp_clean_unexpected": self.fp_clean_unexpected,
            "fp_defects": self.fp_defects,
            "collateral": self.collateral,
            "guard_skipped": self.guard_skipped,
            "guard_reported": self.guard_reported,
        }


@dataclass(frozen=True)
class LayerAudit:
    layer: str
    findings: tuple[Finding, ...]
    crs: str
    metric_guard: bool
    carriers: tuple[str, ...]
    rule_codes: frozenset[str]

    @property
    def guard_reported(self) -> bool:
        return bool(self.carriers)


@dataclass(frozen=True)
class Grid:
    seed: int
    parcels: int
    road_cells: int


def defect_type_of(finding: Finding) -> str | None:
    """Map an audit finding to a benchmark defect type, or None if it maps to none."""
    if finding.code in ENDPOINT_CODES:
        return ENDPOINT_TITLE_TO_DEFECT.get(finding.title)
    return CODE_TO_DEFECT.get(finding.code)


def expected_clean(layer: str, finding: Finding) -> bool:
    return (layer, finding.code, finding.title) in EXPECTED_CLEAN


Reproject = Callable[[BaseGeometry], BaseGeometry]


def to_metres(crs: str) -> Reproject | None:
    """Map geometries from ``crs`` back to the metric base CRS, or None if it is the base."""
    if crs == BASE_CRS:
        return None
    transformer = Transformer.from_crs(crs, BASE_CRS, always_xy=True)
    return lambda geometry: shapely.transform(
        geometry, lambda xy: np.column_stack(transformer.transform(xy[:, 0], xy[:, 1]))
    )


def to_finding(issue: DatasetIssue, back: Reproject | None) -> Finding:
    # Locations are compared in metres, so findings from other CRSs are mapped back.
    wkt = issue.geometry_wkt
    if back is not None and wkt:
        wkt = str(shapely.to_wkt(back(shapely.from_wkt(wkt)), rounding_precision=-1))
    features = (issue.feature_index, issue.related_feature_index)
    return Finding(issue.code, issue.title, frozenset(i for i in features if i is not None), wkt)


def _layer_audit(
    layer: str, result: DatasetAuditResult, profile: QualityProfile, crs: str
) -> LayerAudit:
    # The audit skips metric topology rules when the CRS has angular units; the same
    # helper tells us whether that guard fired, independent of what the output shows.
    metric_guard = _metric_skip_reason(gpd.GeoDataFrame(geometry=[], crs=crs), profile) is not None
    # Where a user can see the skip: the topology check status, or a CRS metadata finding.
    carriers: list[str] = []
    if metric_guard:
        if any(
            check.name == "topology" and check.status is CheckStatus.SKIPPED
            for check in result.checks
        ):
            carriers.append(GUARD_CARRIER)
        carriers += sorted(
            {issue.code for issue in result.issues if issue.code.startswith("META-")}
        )
    rule_codes = frozenset(
        f"TOP-{rule.rule_type.value.upper().replace('_', '-')}" for rule in profile.topology_rules
    )
    back = to_metres(crs)
    return LayerAudit(
        layer,
        tuple(to_finding(issue, back) for issue in result.issues),
        crs,
        metric_guard,
        tuple(carriers),
        rule_codes,
    )


def audit(path: Path, crs: str, names: Sequence[str]) -> dict[str, LayerAudit]:
    """Audit the file under the named profiles, keyed by profile name."""
    known = profiles()
    return {
        name: _layer_audit(
            known[name][0],
            audit_dataset(path, layer=known[name][0], profile=known[name][1]),
            known[name][1],
            crs,
        )
        for name in names
    }


def fit(
    parcels: int, road_cells: int, per_type: int, seed: int
) -> tuple[Grid, gpd.GeoDataFrame, gpd.GeoDataFrame, dict[str, list[Site]]]:
    """Grow the clean grid from the given minimum until every defect type has isolated sites."""
    while True:
        parcel_frame, road_frame = build(parcels, road_cells)
        try:
            sites = plan(list(parcel_frame.geometry), list(road_frame.geometry), per_type, seed)
        except NotEnoughSites as error:
            if error.layer == "parcels":
                cols = math.ceil(math.sqrt(parcels)) + 4
                parcels = cols * cols
            else:
                road_cells += 2
            continue
        return Grid(seed, parcels, road_cells), parcel_frame, road_frame, sites


def write_layers(path: Path, layers: Mapping[str, Sequence[BaseGeometry]], crs: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    for layer, geometries in layers.items():
        frame = gpd.GeoDataFrame(geometry=list(geometries), crs=BASE_CRS)
        frame.to_crs(crs).to_file(path, layer=layer, driver="GPKG")


def score_file(
    defect_type: str,
    audited: LayerAudit,
    baseline: LayerAudit,
    defects: Sequence[Defect],
    geometries: Sequence[BaseGeometry],
    *,
    seed: int,
    ratio_r: float | None,
) -> tuple[Row, Counter[str]]:
    """Score one single-type defect file; also return its unattributed findings by code.

    Findings already on the clean data are subtracted first. Locations are in metres.
    """
    name = PROFILE_OF[defect_type]
    findings = subtract_baseline(audited.findings, baseline.findings)
    matched = match(defects, findings, defect_type_of, geometries)
    split = classify(
        defects,
        [item for position, item in enumerate(findings) if position not in matched.values()],
        (),
        defect_type_of,
        geometries=geometries,
        scored=frozenset({defect_type}),
    )
    typed_clean = [item for item in baseline.findings if defect_type_of(item) == defect_type]
    row = Row(
        defect_type=defect_type,
        profile=name,
        layer=audited.layer,
        crs=audited.crs,
        ratio_r=ratio_r,
        expected_detect=all(item.expected_detect for item in defects),
        seed=seed,
        injected=len(defects),
        found=len(matched),
        fp_clean=len(typed_clean),
        fp_clean_unexpected=sum(
            1 for item in typed_clean if not expected_clean(audited.layer, item)
        ),
        fp_defects=split.fp_defects[defect_type],
        collateral=split.collateral[defect_type],
        guard_skipped=audited.metric_guard and set(RULE_CODES[defect_type]) <= audited.rule_codes,
        guard_reported=audited.guard_reported,
    )
    return row, split.unattributed


BaselineRow = tuple[str, str, str, int, str, str, int, bool]
"""(profile, layer, crs, seed, code, title, count, expected_clean)."""


def clean_baseline(clean: Mapping[str, LayerAudit], seed: int) -> list[BaselineRow]:
    counts = Counter(
        (name, audit.layer, audit.crs, item.code, item.title)
        for name, audit in clean.items()
        for item in audit.findings
    )
    return [
        (name, layer, crs, seed, code, title, count, (layer, code, title) in EXPECTED_CLEAN)
        for (name, layer, crs, code, title), count in sorted(counts.items())
    ]


def aggregate(rows: Sequence[Row]) -> list[Row]:
    """Sum rows per (defect type, CRS, ratio) across seeds."""
    groups: dict[tuple[str, str, float | None], list[Row]] = {}
    for row in rows:
        groups.setdefault((row.defect_type, row.crs, row.ratio_r), []).append(row)
    return [
        replace(
            members[0],
            injected=sum(item.injected for item in members),
            found=sum(item.found for item in members),
            fp_clean=sum(item.fp_clean for item in members),
            fp_clean_unexpected=sum(item.fp_clean_unexpected for item in members),
            fp_defects=sum(item.fp_defects for item in members),
            collateral=sum(item.collateral for item in members),
            guard_skipped=all(item.guard_skipped for item in members),
            guard_reported=all(item.guard_reported for item in members),
        )
        for members in groups.values()
    ]


def write_csv(path: Path, rows: Sequence[Row]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(row.csv_record() for row in rows)


def write_baseline(path: Path, baseline: Sequence[BaselineRow]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["profile", "layer", "crs", "seed", "code", "title", "count", "expected_clean"]
        )
        writer.writerows(baseline)


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


def _tag(crs: str) -> str:
    return crs.replace(":", "_")


def render(
    rows: Sequence[Row],
    unattributed: Counter[tuple[str, str, str]],
    baseline: Sequence[BaselineRow],
    guards: Mapping[tuple[str, str], tuple[bool, tuple[str, ...]]],
    grids: Sequence[Grid],
    *,
    per_type: int,
) -> str:
    seeds = ", ".join(str(grid.seed) for grid in grids)
    lines = [
        "# GeoQC synthetic recall benchmark",
        "",
        f"geoqc {geoqc.__version__}, commit {commit_hash()}, seeds {seeds}, "
        f"{per_type} defects per type per file.",
        "Profiles: generic-polygon and bench-parcels for parcels, jalan for roads.",
        "Grid per seed (grown until every defect has an isolated site): "
        + "; ".join(
            f"seed {grid.seed}: {grid.parcels} parcels, {grid.road_cells} road cells"
            for grid in grids
        )
        + ".",
        f"Defects are built in {BASE_CRS} (metres) and reprojected; tolerances are not converted.",
        "",
        "| defect type | layer | injected | found | recall | ratio_r | expected | 95% CI "
        "| fp_clean | fp_defects | collateral | profile | crs |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for row in aggregate(rows):
        recall, interval = row.recall, row.interval
        shown = "skipped" if recall is None else f"{recall:.0%}"
        ci = "-" if interval is None else f"{interval[0]:.2f}-{interval[1]:.2f}"
        ratio = "single" if row.ratio_r is None else f"{row.ratio_r:g}"
        lines.append(
            f"| {row.defect_type} | {row.layer} | {row.injected} | {row.found} | {shown} | "
            f"{ratio} | {row.expected_detect} | {ci} | {row.fp_clean} | {row.fp_defects} | "
            f"{row.collateral} | {row.profile} | {row.crs} |"
        )
    lines += [
        "",
        "ratio_r = magnitude / tolerance; 'single' types run at one magnitude (exact checks,",
        "or tolerance 0). expected: whether the audit should detect it at that ratio, so for",
        "expected=False rows the recall column is the rate of detections that should not occur.",
        "Matching is one-to-one: each finding scores at most one defect. Findings with no",
        "feature index match by location (within 0.5 m of the defect's features).",
        "Findings already on the clean data (same code, same location) are subtracted first.",
        "fp_clean: findings of that type on the clean data. fp_defects: unmatched findings",
        "of that type on the defect data. collateral: unmatched findings on a defect's",
        "features that the defect is allowed to cause (scoring.ALLOWED_COLLATERAL).",
        "",
        "## Metric-CRS guard",
        "",
        "guard_skipped: the profile's metric topology rules did not run. guard_reported: the",
        "skip is visible in the audit output; 'reported by' names the field or finding code.",
        "A silent skip is guard_skipped=True with guard_reported=False.",
        "",
        "| profile | crs | guard_skipped | guard_reported | reported by |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {name} | {crs} | {skipped} | {bool(carriers)} | {', '.join(carriers) or '-'} |"
        for (name, crs), (skipped, carriers) in sorted(guards.items())
    ]
    lines += [
        "",
        "## Unattributed findings on the defect data",
        "",
        "Findings not scored under that profile and not allowed collateral, over all files.",
        "",
        "| profile | crs | code | count |",
        "| --- | --- | --- | ---: |",
    ]
    lines += [
        f"| {name} | {crs} | {code} | {count} |"
        for (name, crs, code), count in sorted(unattributed.items())
    ]
    if not unattributed:
        lines.append("| - | - | none | 0 |")
    by_crs: Counter[str] = Counter()
    for item in baseline:
        if not item[7]:
            by_crs[item[2]] += item[6]
    lines += [
        "",
        "## Clean-data baseline",
        "",
        "Unexpected findings on the clean data: "
        + (", ".join(f"{crs}: {n}" for crs, n in sorted(by_crs.items())) or "0")
        + f" (must be 0 in {BASE_CRS}).",
        "",
        "| profile | layer | crs | seed | code | title | count | expected_clean |",
        "| --- | --- | --- | ---: | --- | --- | ---: | --- |",
    ]
    lines += [
        f"| {name} | {layer} | {crs} | {seed} | {code} | {title} | {count} | {expected} |"
        for name, layer, crs, seed, code, title, count, expected in baseline
    ]
    if not baseline:
        lines.append("| - | - | - | - | none | - | 0 | - |")
    return "\n".join(lines) + "\n"


def benchmark(
    out: Path,
    *,
    parcels: int,
    road_cells: int,
    per_type: int,
    seed: int = 42,
    seeds: Sequence[int] | None = None,
    crs: Sequence[str] = (BASE_CRS,),
    ratios: Sequence[float] = (DEFAULT_RATIO,),
) -> str:
    """Run the sweep, write truth.csv, recall.csv and fp_clean.csv, and return markdown."""
    rows: list[Row] = []
    truth: list[dict[str, object]] = []
    unattributed: Counter[tuple[str, str, str]] = Counter()
    baseline: list[BaselineRow] = []
    guards: dict[tuple[str, str], tuple[bool, tuple[str, ...]]] = {}
    grids: list[Grid] = []
    for current in seeds if seeds is not None else (seed,):
        grid, parcel_frame, road_frame, sites = fit(parcels, road_cells, per_type, current)
        grids.append(grid)
        base = {"parcels": list(parcel_frame.geometry), "roads": list(road_frame.geometry)}
        for target in crs:
            folder = out / "runs" / _tag(target) / f"seed{current}"
            clean_path = folder / "clean.gpkg"
            write_layers(clean_path, base, target)
            clean = audit(clean_path, target, list(profiles()))
            baseline += clean_baseline(clean, current)
            for name, layer_audit in clean.items():
                guards[(name, target)] = (layer_audit.metric_guard, layer_audit.carriers)
            for defect_type in DEFECT_TYPES:
                layer, name = LAYER_OF[defect_type], PROFILE_OF[defect_type]
                for ratio in ratios if defect_type in SWEPT else (None,):
                    geometries, defects = apply(defect_type, sites[defect_type], base[layer], ratio)
                    suffix = "" if ratio is None else f"_r{ratio:g}"
                    path = folder / f"{defect_type}{suffix}.gpkg"
                    write_layers(path, {layer: geometries}, target)
                    print(f"auditing {path.relative_to(out)}", file=sys.stderr, flush=True)
                    audited = audit(path, target, [name])[name]
                    row, extra = score_file(
                        defect_type,
                        audited,
                        clean[name],
                        defects,
                        geometries,
                        seed=current,
                        ratio_r=ratio,
                    )
                    rows.append(row)
                    unattributed.update({(name, target, code): n for code, n in extra.items()})
                    truth += [truth_record(item, target, current) for item in defects]
    write_truth(out / "truth.csv", truth)
    write_csv(out / "recall.csv", rows)
    write_baseline(out / "fp_clean.csv", baseline)
    return render(rows, unattributed, baseline, guards, grids, per_type=per_type)


def _floats(text: str) -> tuple[float, ...]:
    return tuple(float(item) for item in text.split(",") if item.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parcels", type=int, default=400, help="minimum parcel count")
    parser.add_argument("--road-cells", type=int, default=10, help="minimum road grid size")
    parser.add_argument("--per-type", type=int, default=100)
    parser.add_argument("--seeds", type=int, default=5, help="number of seeds")
    parser.add_argument("--seed", type=int, default=42, help="first seed")
    parser.add_argument("--crs", default=f"{BASE_CRS},EPSG:4326")
    parser.add_argument("--ratios", default="0.5,0.9,1.1,2,10")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="per-type 20, 1 seed, ratios 0.5,2, both CRS; runs twice to check determinism",
    )
    parser.add_argument("--out", type=Path, default=HERE / "out")
    args = parser.parse_args()
    per_type, seed_count, ratios = args.per_type, args.seeds, _floats(args.ratios)
    if args.quick:
        per_type, seed_count, ratios = QUICK_PER_TYPE, QUICK_SEEDS, QUICK_RATIOS
    args.out.mkdir(parents=True, exist_ok=True)

    def run_once() -> str:
        return benchmark(
            args.out,
            parcels=args.parcels,
            road_cells=args.road_cells,
            per_type=per_type,
            seeds=tuple(range(args.seed, args.seed + seed_count)),
            crs=tuple(item.strip() for item in args.crs.split(",") if item.strip()),
            ratios=ratios,
        )

    outputs = ("truth.csv", "recall.csv", "fp_clean.csv")
    first = run_once()
    first_files = [(args.out / name).read_text(encoding="utf-8") for name in outputs]
    print(first)
    (args.out / "recall_summary.md").write_text(first, encoding="utf-8")
    if args.quick:
        # Run the whole pipeline again from scratch: the outputs must match. Only under
        # --quick, because a full sweep takes hours.
        second = run_once()
        second_files = [(args.out / name).read_text(encoding="utf-8") for name in outputs]
        if first != second or first_files != second_files:
            sys.exit("Runs differ: the benchmark is not deterministic.")
    with (args.out / "fp_clean.csv").open(encoding="utf-8") as handle:
        unexpected = [
            row
            for row in csv.DictReader(handle)
            if row["expected_clean"] == "False" and row["crs"] == BASE_CRS
        ]
    if unexpected:
        sys.exit(f"Unexpected findings on the clean data in {BASE_CRS}: {unexpected}")


if __name__ == "__main__":
    main()
