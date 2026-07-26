"""Shapely adapter that repairs topology with minimal shape change.

Single-geometry defects are fixed with GEOS ``make_valid`` (preserving as much
of the original as possible), duplicate vertices with ``remove_repeated_points``,
and degenerate slivers by dropping sub-threshold parts. Cross-feature overlaps
are resolved with a deterministic *erase* policy (earlier features keep disputed
area); enclosed gaps below the configured area are merged into the neighbour
with the longest shared boundary. Detection reuses
:class:`ShapelyGeometryValidator`, so the repairer and the validator never
disagree about what is wrong.
"""

from collections.abc import Sequence
from math import tau

import shapely
from shapely import is_valid_reason
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from geoqc.domain.models.geometry_validation import GeometryIssueType
from geoqc.domain.models.topology_repair import (
    CoverageRepairResult,
    FeatureRepairResult,
    GeometryRepairResult,
    RepairAction,
    RepairConfig,
    RepairIssueType,
    RepairMetrics,
    RepairReport,
    RepairStatus,
)
from geoqc.infrastructure.gis.shapely_geometry_validator import ShapelyGeometryValidator

_AREA_EPSILON = 1e-12


class ShapelyTopologyRepairer:
    """Repair intrinsic geometry defects and cross-feature coverage errors."""

    def __init__(self, validator: ShapelyGeometryValidator | None = None) -> None:
        self._validator = validator or ShapelyGeometryValidator()

    def repair(self, wkt: str, config: RepairConfig) -> GeometryRepairResult:
        """Repair the intrinsic topology of a single WKT geometry."""
        original = shapely.from_wkt(wkt)
        try:
            repaired, actions = self._repair_geometry(original, config)
        except shapely.errors.ShapelyError:
            return self._build_result(original, original, [], failed=True)
        return self._build_result(original, repaired, actions)

    def repair_coverage(self, wkts: Sequence[str], config: RepairConfig) -> CoverageRepairResult:
        """Repair a set of geometries as one topological coverage."""
        originals = [shapely.from_wkt(wkt) for wkt in wkts]
        repaired: list[BaseGeometry] = []
        actions: list[list[RepairAction]] = []
        failures: list[str | None] = []
        for geometry in originals:
            try:
                fixed, fixed_actions = self._repair_geometry(geometry, config)
                failure = self._safety_failure(geometry, fixed, config)
            except (shapely.errors.ShapelyError, ValueError) as error:
                repaired.append(geometry)
                actions.append([])
                failures.append(str(error) or error.__class__.__name__)
                continue
            repaired.append(geometry if failure else fixed)
            actions.append(list(fixed_actions))
            failures.append(failure)

        try:
            if config.resolve_overlaps:
                self._resolve_overlaps(repaired, actions)
            if config.fill_gaps:
                self._fill_gaps(repaired, actions, config)
        except (shapely.errors.ShapelyError, ValueError):
            # Cross-feature operations are atomic: never expose a partial coverage.
            repaired = list(originals)
            actions = [[] for _ in originals]
            failures = ["Coverage repair failed and was rolled back atomically." for _ in originals]

        for index, candidate in enumerate(repaired):
            failure = failures[index] or self._safety_failure(originals[index], candidate, config)
            if failure:
                repaired[index] = originals[index]
                failures[index] = failure

        results = tuple(
            FeatureRepairResult(
                index,
                self._build_result(
                    originals[index], repaired[index], acts, failure_reason=failures[index]
                ),
            )
            for index, acts in enumerate(actions)
        )
        return CoverageRepairResult(
            before_wkt=tuple(self._to_wkt(geometry) for geometry in originals),
            after_wkt=tuple(self._to_wkt(geometry) for geometry in repaired),
            report=RepairReport(results),
        )

    # -- single geometry --------------------------------------------------

    def _repair_geometry(
        self, geometry: BaseGeometry, config: RepairConfig
    ) -> tuple[BaseGeometry, list[RepairAction]]:
        actions: list[RepairAction] = []
        current = geometry

        if config.remove_duplicate_vertices:
            deduplicated = shapely.remove_repeated_points(
                current, config.duplicate_vertex_tolerance
            )
            if self._vertex_count(deduplicated) < self._vertex_count(current):
                actions.append(
                    RepairAction(
                        RepairIssueType.DUPLICATE_VERTEX,
                        "remove_repeated_points",
                        "Removed coincident consecutive vertices.",
                    )
                )
                current = deduplicated

        if config.fix_invalid and not current.is_valid:
            detected = {issue.issue_type for issue in self._validator.validate(current).issues}
            reason = is_valid_reason(current) or "invalid geometry"
            added = False
            if GeometryIssueType.RING_ERROR in detected:
                actions.append(RepairAction(RepairIssueType.INVALID_RING, "make_valid", reason))
                added = True
            if GeometryIssueType.SELF_INTERSECTION in detected:
                actions.append(
                    RepairAction(RepairIssueType.SELF_INTERSECTION, "make_valid", reason)
                )
                added = True
            if not added:
                actions.append(
                    RepairAction(RepairIssueType.SELF_INTERSECTION, "make_valid", reason)
                )
            current = shapely.make_valid(current)

        if config.remove_slivers:
            cleaned, removed = self._remove_slivers(current, config)
            if removed > 0:
                actions.append(
                    RepairAction(
                        RepairIssueType.SLIVER_POLYGON,
                        "drop_sliver_parts",
                        f"Removed {removed} sub-threshold sliver part(s).",
                    )
                )
                current = cleaned

        return current, actions

    def _remove_slivers(
        self, geometry: BaseGeometry, config: RepairConfig
    ) -> tuple[BaseGeometry, int]:
        parts = self._leaf_parts(geometry)
        polygon_count = sum(1 for part in parts if isinstance(part, Polygon))
        if polygon_count == 0:
            return geometry, 0

        kept: list[BaseGeometry] = []
        removed = 0
        for part in parts:
            if isinstance(part, Polygon) and self._is_sliver(part, config):
                removed += 1
                continue
            kept.append(part)

        if removed == 0 or not kept:
            return geometry, 0
        return self._combine(kept), removed

    @staticmethod
    def _is_sliver(polygon: Polygon, config: RepairConfig) -> bool:
        area = polygon.area
        if area < config.sliver_area_threshold:
            return True
        perimeter = polygon.length
        if perimeter <= 0.0:
            return True
        thinness = (2.0 * tau * area) / (perimeter * perimeter)
        return thinness < config.sliver_thinness_threshold

    # -- coverage ---------------------------------------------------------

    def _resolve_overlaps(
        self, repaired: list[BaseGeometry], actions: list[list[RepairAction]]
    ) -> None:
        placed: BaseGeometry | None = None
        for index, geometry in enumerate(repaired):
            if not self._is_polygonal(geometry):
                continue
            if placed is not None:
                overlap = geometry.intersection(placed)
                if not overlap.is_empty and overlap.area > _AREA_EPSILON:
                    reduced = geometry.difference(placed)
                    actions[index].append(
                        RepairAction(
                            RepairIssueType.OVERLAP,
                            "erase_overlap",
                            f"Removed {overlap.area:.6g} overlapping area.",
                        )
                    )
                    repaired[index] = reduced
                    geometry = reduced
            placed = geometry if placed is None else shapely.union(placed, geometry)

    def _fill_gaps(
        self,
        repaired: list[BaseGeometry],
        actions: list[list[RepairAction]],
        config: RepairConfig,
    ) -> None:
        polygon_indices = [
            index for index, geometry in enumerate(repaired) if self._is_polygonal(geometry)
        ]
        if not polygon_indices:
            return
        covered = shapely.union_all([repaired[index] for index in polygon_indices])
        for hole in self._small_holes(covered, config.gap_area_threshold):
            target = self._widest_neighbour(hole, repaired, polygon_indices)
            if target is None:
                continue
            repaired[target] = shapely.union(repaired[target], hole)
            actions[target].append(
                RepairAction(
                    RepairIssueType.GAP,
                    "fill_gap",
                    f"Filled {hole.area:.6g} enclosed gap area.",
                )
            )

    def _small_holes(self, geometry: BaseGeometry, threshold: float) -> list[Polygon]:
        holes: list[Polygon] = []
        for polygon in self._polygon_parts(geometry):
            for ring in polygon.interiors:
                candidate = Polygon(ring)
                if _AREA_EPSILON < candidate.area < threshold:
                    holes.append(candidate)
        return holes

    @staticmethod
    def _widest_neighbour(
        hole: Polygon, repaired: Sequence[BaseGeometry], polygon_indices: Sequence[int]
    ) -> int | None:
        best_index: int | None = None
        best_length = 0.0
        boundary = hole.boundary
        for index in polygon_indices:
            shared = repaired[index].boundary.intersection(boundary).length
            if shared > best_length:
                best_length = shared
                best_index = index
        return best_index

    # -- helpers ----------------------------------------------------------

    def _build_result(
        self,
        before: BaseGeometry,
        after: BaseGeometry,
        actions: Sequence[RepairAction],
        *,
        failed: bool = False,
        failure_reason: str | None = None,
    ) -> GeometryRepairResult:
        before_wkt = self._to_wkt(before)
        if failed or failure_reason:
            status = RepairStatus.FAILED
            after = before
            actions = ()
        elif not actions:
            status = RepairStatus.UNCHANGED
            after = before
        elif after.is_valid:
            status = RepairStatus.REPAIRED
        else:
            status = RepairStatus.FAILED
        after_wkt = self._to_wkt(after)
        metrics = RepairMetrics(
            area_before=before.area,
            area_after=after.area,
            vertex_count_before=self._vertex_count(before),
            vertex_count_after=self._vertex_count(after),
            shape_shift=self._shape_shift(before, after),
        )
        return GeometryRepairResult(
            geometry_type=before.geom_type,
            status=status,
            before_wkt=before_wkt,
            after_wkt=after_wkt,
            actions=tuple(actions),
            metrics=metrics,
            failure_reason=failure_reason or ("Repair operation failed." if failed else None),
        )

    def _safety_failure(
        self, before: BaseGeometry, after: BaseGeometry, config: RepairConfig
    ) -> str | None:
        """Reject candidates that violate explicit minimal-change guarantees."""
        if not after.is_valid:
            return "Candidate geometry is invalid."
        if not before.is_empty and after.is_empty:
            return "Candidate repair would erase the entire geometry."
        if self._is_polygonal(before) and not self._is_polygonal(after):
            return "Candidate repair changed a polygon into a non-polygon geometry."
        shift = self._shape_shift(before, after)
        if config.max_shape_shift is not None and shift > config.max_shape_shift:
            return "Candidate exceeds max_shape_shift."
        if config.max_relative_area_change is not None and before.area > _AREA_EPSILON:
            relative_change = abs(after.area - before.area) / before.area
            if relative_change > config.max_relative_area_change:
                return "Candidate exceeds max_relative_area_change."
        return None

    @staticmethod
    def _shape_shift(before: BaseGeometry, after: BaseGeometry) -> float:
        if before.is_empty or after.is_empty:
            return 0.0
        return float(before.hausdorff_distance(after))

    @staticmethod
    def _vertex_count(geometry: BaseGeometry) -> int:
        return int(shapely.get_num_coordinates(geometry))

    @staticmethod
    def _to_wkt(geometry: BaseGeometry) -> str:
        return str(shapely.to_wkt(geometry, rounding_precision=-1))

    @staticmethod
    def _is_polygonal(geometry: BaseGeometry) -> bool:
        return isinstance(geometry, (Polygon, MultiPolygon)) and not geometry.is_empty

    def _polygon_parts(self, geometry: BaseGeometry) -> list[Polygon]:
        return [part for part in self._leaf_parts(geometry) if isinstance(part, Polygon)]

    @staticmethod
    def _leaf_parts(geometry: BaseGeometry) -> list[BaseGeometry]:
        parts: list[BaseGeometry] = []
        stack: list[BaseGeometry] = [geometry]
        while stack:
            current = stack.pop()
            if isinstance(current, (MultiPolygon, GeometryCollection)):
                stack.extend(reversed(list(current.geoms)))
            elif not current.is_empty:
                parts.append(current)
        return parts

    @staticmethod
    def _combine(parts: Sequence[BaseGeometry]) -> BaseGeometry:
        if len(parts) == 1:
            return parts[0]
        polygons = [part for part in parts if isinstance(part, Polygon)]
        if len(polygons) == len(parts):
            return MultiPolygon(polygons)
        return GeometryCollection(list(parts))
