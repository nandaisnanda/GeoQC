"""Pure scoring for the recall benchmark: one-to-one matching, Wilson intervals, FP split."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

import shapely
from shapely.geometry.base import BaseGeometry


class DefectLike(Protocol):
    @property
    def defect_type(self) -> str: ...

    @property
    def feature_index(self) -> int: ...

    @property
    def related_index(self) -> int: ...


@dataclass(frozen=True)
class Finding:
    """One audit finding reduced to what scoring needs. ``wkt`` is its location."""

    code: str
    title: str
    features: frozenset[int]
    wkt: str = ""


TypeMap = Callable[[Finding], "str | None"]

# (defect type, finding type) pairs a defect is allowed to cause besides its own finding.
# The finding type may be the benchmark defect type it maps to or its raw code.
ALLOWED_COLLATERAL: frozenset[tuple[str, str]] = frozenset(
    {
        # The baseline duplicate check sees the exact copy too.
        ("duplicate_segment_full", "TOP-NO-DUPLICATE"),
        # Both ends of the partial copy lie mid-road, on the original, without a node. The
        # audit emits TOP-NO-DANGLES titled "T-junction not noded", which run.py maps to
        # unnoded_t_junction. The mapped type is narrower than the raw code, which would
        # also admit "Dangling endpoint" and "Possible undershoot".
        ("duplicate_segment_partial", "unnoded_t_junction"),
        ("undershoot", "overshoot"),
        ("overshoot", "undershoot"),
        # The overshooting stem crosses the through road without a node, and its moved
        # end no longer meets any segment end.
        ("overshoot", "ROAD-UNNODED_INTERSECTION"),
        ("overshoot", "TOP-NO-DANGLES"),
        ("self_intersection", "TOP-NO-GAP"),
        ("unnoded_t_junction", "ROAD-UNNODED_INTERSECTION"),
        # The spike's two base vertices cannot sit on the 0.001 m grid: their spacing
        # fixes the apex angle exactly.
        ("spike", "TOP-PRECISION-GRID"),
        # Only for spacings that are not a multiple of the 0.001 m grid step (none of the
        # default ratios): the inserted vertex then has to sit off the grid.
        ("min_vertex_distance", "TOP-PRECISION-GRID"),
    }
)
LOCATION_BUFFER = 0.5


def defect_features(defect: DefectLike) -> frozenset[int]:
    return frozenset(i for i in (defect.feature_index, defect.related_index) if i >= 0)


def finding_type(finding: Finding, type_map: TypeMap) -> str:
    return type_map(finding) or finding.code


class _Locator:
    """Decides whether a finding lies on a defect.

    A finding that names features is on a defect when it names one of the defect's
    features. A finding that names none (a coverage gap, for instance) falls back to
    location: its geometry must intersect the union of the defect's feature geometries
    buffered by ``buffer`` CRS units.
    """

    def __init__(
        self,
        defects: Sequence[DefectLike],
        geometries: Sequence[BaseGeometry] | None,
        buffer: float,
    ) -> None:
        self.defects = defects
        self.geometries = geometries
        self.buffer = buffer
        self._zones: dict[int, BaseGeometry] = {}
        self._shapes: dict[str, BaseGeometry] = {}

    def _zone(self, position: int) -> BaseGeometry:
        if position not in self._zones:
            assert self.geometries is not None
            parts = [self.geometries[i] for i in sorted(defect_features(self.defects[position]))]
            self._zones[position] = shapely.union_all(parts).buffer(self.buffer)
        return self._zones[position]

    def on(self, finding: Finding, position: int) -> bool:
        if finding.features:
            return bool(finding.features & defect_features(self.defects[position]))
        if self.geometries is None or not finding.wkt:
            return False
        if finding.wkt not in self._shapes:
            self._shapes[finding.wkt] = shapely.from_wkt(finding.wkt)
        return bool(self._shapes[finding.wkt].intersects(self._zone(position)))


def match(
    defects: Sequence[DefectLike],
    findings: Sequence[Finding],
    type_map: TypeMap,
    geometries: Sequence[BaseGeometry] | None = None,
    buffer: float = LOCATION_BUFFER,
) -> dict[int, int]:
    """Maximum one-to-one matching, returned as {defect position: finding position}.

    Finding f can match defect j when f maps to j's type and lies on j (see _Locator;
    ``geometries`` are the layer's features by index, needed only for the location
    fallback). Each defect and each finding is used at most once. Augmenting paths keep
    the count maximal whatever the visiting order.
    """
    locator = _Locator(defects, geometries, buffer)
    types = [type_map(item) for item in findings]
    candidates = [
        [
            position
            for position, finding in enumerate(findings)
            if types[position] == defect.defect_type and locator.on(finding, index)
        ]
        for index, defect in enumerate(defects)
    ]
    owner: dict[int, int] = {}

    def augment(defect: int, seen: set[int]) -> bool:
        for position in candidates[defect]:
            if position in seen:
                continue
            seen.add(position)
            if position not in owner or augment(owner[position], seen):
                owner[position] = defect
                return True
        return False

    for defect in range(len(defects)):
        augment(defect, set())
    return {defect: position for position, defect in owner.items()}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    # At k=0 and k=n the bounds are exactly 0 and 1; pin them against rounding.
    low = 0.0 if k == 0 else max(0.0, centre - half)
    high = 1.0 if k == n else min(1.0, centre + half)
    return (low, high)


@dataclass(frozen=True)
class Unmatched:
    """Unmatched findings split into collateral and false positives.

    collateral is keyed by the defect type that caused it, fp_defects by the type the
    finding maps to. Findings that map to no scored type and are not collateral land in
    ``unattributed``, keyed by code.
    """

    collateral: Counter[str]
    fp_defects: Counter[str]
    unattributed: Counter[str]


def classify(
    defects: Sequence[DefectLike],
    findings: Sequence[Finding],
    matched: Iterable[int],
    type_map: TypeMap,
    *,
    geometries: Sequence[BaseGeometry] | None = None,
    buffer: float = LOCATION_BUFFER,
    scored: frozenset[str] | None = None,
    allowed: frozenset[tuple[str, str]] = ALLOWED_COLLATERAL,
) -> Unmatched:
    """Split unmatched findings. ``scored`` limits fp_defects to those types (None: all)."""
    locator = _Locator(defects, geometries, buffer)
    used = set(matched)
    collateral: Counter[str] = Counter()
    fp_defects: Counter[str] = Counter()
    unattributed: Counter[str] = Counter()
    for position, finding in enumerate(findings):
        if position in used:
            continue
        kinds = {finding_type(finding, type_map), finding.code}
        cause = next(
            (
                defect.defect_type
                for index, defect in enumerate(defects)
                if any((defect.defect_type, kind) in allowed for kind in kinds)
                and locator.on(finding, index)
            ),
            None,
        )
        mapped = type_map(finding)
        if cause is not None:
            collateral[cause] += 1
        elif mapped is not None and (scored is None or mapped in scored):
            fp_defects[mapped] += 1
        else:
            unattributed[finding.code] += 1
    return Unmatched(collateral, fp_defects, unattributed)


def subtract_baseline(findings: Sequence[Finding], baseline: Sequence[Finding]) -> list[Finding]:
    """Drop findings that already occur on the clean data: same code at the same location.

    Location, not feature index, identifies a baseline finding, because injection can
    renumber features (removed road segments, appended sliver parcels).
    """
    remaining = Counter((item.code, item.wkt) for item in baseline)
    kept = []
    for item in findings:
        key = (item.code, item.wkt)
        if remaining[key]:
            remaining[key] -= 1
            continue
        kept.append(item)
    return kept
