"""Scalable Shapely implementations for enterprise spatial intelligence."""

from collections.abc import Callable, Sequence
from math import hypot

import shapely
from shapely import STRtree
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from geoqc.domain.models.enterprise_spatial import (
    ConflictPolicy,
    ConflictType,
    DatasetDifferenceReport,
    DatasetSnapshot,
    DifferenceKind,
    DuplicatePair,
    FeatureDifference,
    SpatialConflict,
    SpatialConflictReport,
    SpatialDuplicateConfig,
    SpatialDuplicateReport,
    SpatialLayer,
)


def _load_many(values: Sequence[str]) -> list[BaseGeometry]:
    geometries: list[BaseGeometry] = []
    for value in values:
        geometry = shapely.from_wkt(value)
        if geometry is None or geometry.is_empty:
            raise ValueError("geometries must be non-empty valid WKT")
        geometries.append(geometry)
    return geometries


def _wkt(geometry: BaseGeometry) -> str:
    return str(shapely.to_wkt(geometry, rounding_precision=-1))


def _measure(geometry: BaseGeometry) -> float:
    return geometry.area if geometry.area > 0 else geometry.length


def _iou(left: BaseGeometry, right: BaseGeometry) -> float:
    intersection = _measure(left.intersection(right))
    union = _measure(left.union(right))
    if union == 0:
        return float(left.equals(right))
    return max(0.0, min(1.0, intersection / union))


def _hausdorff_similarity(left: BaseGeometry, right: BaseGeometry) -> float:
    min_x = min(left.bounds[0], right.bounds[0])
    min_y = min(left.bounds[1], right.bounds[1])
    max_x = max(left.bounds[2], right.bounds[2])
    max_y = max(left.bounds[3], right.bounds[3])
    scale = hypot(max_x - min_x, max_y - min_y)
    distance = left.hausdorff_distance(right)
    if scale == 0:
        return float(distance == 0)
    return max(0.0, 1.0 - distance / scale)


def _shape_similarity(left: BaseGeometry, right: BaseGeometry) -> float:
    left_measure, right_measure = _measure(left), _measure(right)
    if max(left_measure, right_measure) == 0:
        measure_ratio = float(left.equals(right))
    else:
        measure_ratio = min(left_measure, right_measure) / max(left_measure, right_measure)
    left_envelope, right_envelope = left.envelope.area, right.envelope.area
    left_fill = left.area / left_envelope if left_envelope else 1.0
    right_fill = right.area / right_envelope if right_envelope else 1.0
    fill_similarity = 1.0 - abs(left_fill - right_fill)
    return max(0.0, min(1.0, (measure_ratio + fill_similarity) / 2.0))


def _similarities(left: BaseGeometry, right: BaseGeometry) -> tuple[float, float, float]:
    return _iou(left, right), _hausdorff_similarity(left, right), _shape_similarity(left, right)


def _query_geometry(geometry: BaseGeometry, tolerance: float) -> BaseGeometry:
    if tolerance == 0:
        return geometry.envelope
    min_x, min_y, max_x, max_y = geometry.bounds
    return box(min_x - tolerance, min_y - tolerance, max_x + tolerance, max_y + tolerance)


class ShapelySpatialDuplicateDetector:
    """Generate candidates with STRtree, then evaluate expensive shape metrics."""

    def detect(
        self, geometries_wkt: Sequence[str], config: SpatialDuplicateConfig
    ) -> SpatialDuplicateReport:
        geometries = _load_many(geometries_wkt)
        tree = STRtree(geometries)
        candidates: set[tuple[int, int]] = set()
        truncated = False
        for left_index, geometry in enumerate(geometries):
            for raw_index in tree.query(_query_geometry(geometry, config.search_tolerance)):
                right_index = int(raw_index)
                if right_index <= left_index:
                    continue
                candidates.add((left_index, right_index))
                if len(candidates) >= config.maximum_pairs:
                    truncated = True
                    break
            if truncated:
                break

        pairs: list[DuplicatePair] = []
        for left_index, right_index in sorted(candidates):
            left, right = geometries[left_index], geometries[right_index]
            iou, hausdorff, shape = _similarities(left, right)
            weights = config.weights
            similarity = weights.iou * iou + weights.hausdorff * hausdorff + weights.shape * shape
            if similarity + 1e-12 < config.similarity_threshold:
                continue
            pairs.append(
                DuplicatePair(
                    left_index=left_index,
                    right_index=right_index,
                    similarity_percent=round(similarity * 100, 4),
                    iou=round(iou, 6),
                    hausdorff_similarity=round(hausdorff, 6),
                    shape_similarity=round(shape, 6),
                    exact=left.equals(right),
                    left_wkt=_wkt(left),
                    right_wkt=_wkt(right),
                )
            )
        possible = len(geometries) * (len(geometries) - 1) // 2
        return SpatialDuplicateReport(
            feature_count=len(geometries),
            possible_pairs=possible,
            candidate_pairs=len(candidates),
            evaluated_pairs=len(candidates),
            pairs=tuple(
                sorted(
                    pairs,
                    key=lambda item: (-item.similarity_percent, item.left_index, item.right_index),
                )
            ),
            truncated=truncated,
        )


class ShapelyDatasetComparator:
    """Compare two snapshots using one-to-one spatially indexed matching."""

    def compare(
        self, left: DatasetSnapshot, right: DatasetSnapshot, *, match_threshold: float = 0.5
    ) -> DatasetDifferenceReport:
        if not 0 <= match_threshold <= 1:
            raise ValueError("match_threshold must be between zero and one")
        left_geometries = _load_many(left.geometries_wkt)
        right_geometries = _load_many(right.geometries_wkt)
        tree = STRtree(right_geometries) if right_geometries else None
        candidates: list[tuple[float, int, int]] = []
        if tree is not None:
            for left_index, geometry in enumerate(left_geometries):
                for raw_index in tree.query(geometry.envelope):
                    right_index = int(raw_index)
                    score = sum(_similarities(geometry, right_geometries[right_index])) / 3
                    if score >= match_threshold:
                        candidates.append((score, left_index, right_index))
        matched_left: set[int] = set()
        matched_right: set[int] = set()
        differences: list[FeatureDifference] = []
        for score, left_index, right_index in sorted(candidates, reverse=True):
            if left_index in matched_left or right_index in matched_right:
                continue
            matched_left.add(left_index)
            matched_right.add(right_index)
            left_attributes = left.attributes[left_index] if left.attributes else {}
            right_attributes = right.attributes[right_index] if right.attributes else {}
            changed = tuple(
                sorted(
                    key
                    for key in set(left_attributes) | set(right_attributes)
                    if left_attributes.get(key) != right_attributes.get(key)
                )
            )
            exact_geometry = left_geometries[left_index].equals(right_geometries[right_index])
            kind = (
                DifferenceKind.UNCHANGED
                if exact_geometry and not changed
                else DifferenceKind.MODIFIED
            )
            differences.append(
                FeatureDifference(
                    kind,
                    left_index,
                    right_index,
                    round(score * 100, 4),
                    changed,
                    _wkt(left_geometries[left_index]),
                    _wkt(right_geometries[right_index]),
                )
            )
        for index, geometry in enumerate(left_geometries):
            if index not in matched_left:
                differences.append(
                    FeatureDifference(
                        DifferenceKind.REMOVED, index, None, 0, left_wkt=_wkt(geometry)
                    )
                )
        for index, geometry in enumerate(right_geometries):
            if index not in matched_right:
                differences.append(
                    FeatureDifference(
                        DifferenceKind.ADDED, None, index, 0, right_wkt=_wkt(geometry)
                    )
                )

        left_boundary = (
            unary_union(left_geometries) if left_geometries else shapely.GeometryCollection()
        )
        right_boundary = (
            unary_union(right_geometries) if right_geometries else shapely.GeometryCollection()
        )
        left_keys, right_keys = set(left.schema), set(right.schema)
        warnings = (
            ()
            if left.crs == right.crs
            else ("CRS mismatch: coordinates were compared without reprojection",)
        )
        return DatasetDifferenceReport(
            left.name,
            right.name,
            left.crs == right.crs,
            left.crs,
            right.crs,
            tuple(sorted(right_keys - left_keys)),
            tuple(sorted(left_keys - right_keys)),
            tuple(
                sorted(
                    key for key in left_keys & right_keys if left.schema[key] != right.schema[key]
                )
            ),
            round(_iou(left_boundary, right_boundary), 6),
            round(_measure(left_boundary.symmetric_difference(right_boundary)), 6),
            tuple(
                sorted(
                    differences,
                    key=lambda item: (
                        item.kind.value,
                        item.left_index or -1,
                        item.right_index or -1,
                    ),
                )
            ),
            len(candidates),
            warnings,
        )


class ShapelySpatialConflictAnalyzer:
    """Apply deterministic cross-layer conflict policies after STRtree joins."""

    def analyze(
        self, layers: Sequence[SpatialLayer], policy: ConflictPolicy | None = None
    ) -> SpatialConflictReport:
        policy = policy or ConflictPolicy()
        conflicts: list[SpatialConflict] = []
        candidate_count = 0
        for layer_index, left_layer in enumerate(layers):
            left_geometries = _load_many(left_layer.geometries_wkt)
            for right_layer in layers[layer_index + 1 :]:
                rule = self._rule(left_layer, right_layer)
                if rule is None:
                    continue
                right_geometries = _load_many(right_layer.geometries_wkt)
                tree = STRtree(right_geometries)
                for left_index, left_geometry in enumerate(left_geometries):
                    for raw_index in tree.query(left_geometry.envelope):
                        right_index = int(raw_index)
                        candidate_count += 1
                        right_geometry = right_geometries[right_index]
                        intersection = left_geometry.intersection(right_geometry)
                        if intersection.is_empty:
                            continue
                        conflict_type, base = rule(policy)
                        magnitude = self._magnitude(left_geometry, right_geometry, intersection)
                        conflicts.append(
                            SpatialConflict(
                                conflict_type,
                                left_layer.name,
                                right_layer.name,
                                left_index,
                                right_index,
                                round(min(100.0, base + policy.magnitude_weight * magnitude), 2),
                                round(magnitude, 6),
                                self._message(conflict_type),
                                _wkt(intersection),
                            )
                        )
        return SpatialConflictReport(
            tuple(
                sorted(
                    conflicts,
                    key=lambda item: (-item.severity_score, item.left_layer, item.left_index),
                )
            ),
            candidate_count,
        )

    @staticmethod
    def _rule(
        left: SpatialLayer, right: SpatialLayer
    ) -> Callable[[ConflictPolicy], tuple[ConflictType, float]] | None:
        roles = {left.role.lower(), right.role.lower()}
        if roles == {"road", "river"}:
            return lambda policy: (ConflictType.ROAD_RIVER_CROSSING, policy.road_river_base)
        if roles == {"building", "river"}:
            return lambda policy: (ConflictType.BUILDING_IN_RIVER, policy.building_river_base)
        if roles == {"boundary"}:
            return lambda policy: (ConflictType.BOUNDARY_CONFLICT, policy.boundary_base)
        if left.agency and right.agency and left.agency != right.agency:
            return lambda policy: (ConflictType.INTER_AGENCY_OVERLAP, policy.overlap_base)
        return None

    @staticmethod
    def _magnitude(left: BaseGeometry, right: BaseGeometry, intersection: BaseGeometry) -> float:
        denominator = min(_measure(left), _measure(right))
        return min(1.0, _measure(intersection) / denominator) if denominator else 1.0

    @staticmethod
    def _message(conflict_type: ConflictType) -> str:
        return {
            ConflictType.ROAD_RIVER_CROSSING: "Road intersects a river feature",
            ConflictType.BUILDING_IN_RIVER: "Building occupies a river feature",
            ConflictType.INTER_AGENCY_OVERLAP: "Features from different agencies overlap",
            ConflictType.BOUNDARY_CONFLICT: "Administrative boundaries overlap",
        }[conflict_type]
