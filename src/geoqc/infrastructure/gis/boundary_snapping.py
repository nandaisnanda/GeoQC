"""Shapely boundary snapping adapter."""

from collections.abc import Sequence

import shapely
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from geoqc.domain.models.spatial_intelligence import (
    BoundarySnapConfig,
    BoundarySnapFeature,
    BoundarySnapResult,
)
from geoqc.infrastructure.gis.spatial_helpers import _loads, _wkt


class ShapelyBoundarySnapper:
    """Snap nearby polygon vertices while enforcing strict safety limits."""

    def snap(self, geometries_wkt: Sequence[str], config: BoundarySnapConfig) -> BoundarySnapResult:
        original = _loads(geometries_wkt)
        if any(g.geom_type not in {"Polygon", "MultiPolygon"} for g in original):
            raise ValueError("boundary snap accepts only Polygon and MultiPolygon geometries")
        tree = STRtree(original)
        neighbours: list[set[int]] = [set() for _ in original]
        pairs: set[tuple[int, int]] = set()
        for index, geometry in enumerate(original):
            for candidate in tree.query(geometry.buffer(config.tolerance)):
                other = int(candidate)
                if other <= index:
                    continue
                distance = geometry.boundary.distance(original[other].boundary)
                if 0 < distance <= config.tolerance and not geometry.intersects(original[other]):
                    pairs.add((index, other))
                    # Move only the later feature toward a stable earlier anchor.
                    # Symmetric snapping can make both polygons cross the gap and overlap.
                    neighbours[other].add(index)

        output: list[BoundarySnapFeature] = []
        for index, before in enumerate(original):
            references = [original[item].boundary for item in sorted(neighbours[index])]
            candidate = before
            for reference in references:
                candidate = shapely.snap(candidate, reference, config.tolerance)
            output.append(
                self._assess(index, before, candidate, neighbours[index], original, config)
            )
        return BoundarySnapResult(tuple(output), len(pairs))

    def _assess(
        self,
        index: int,
        before: BaseGeometry,
        after: BaseGeometry,
        neighbours: set[int],
        all_geometries: Sequence[BaseGeometry],
        config: BoundarySnapConfig,
    ) -> BoundarySnapFeature:
        area_before = before.area
        area_after = after.area
        shift = before.hausdorff_distance(after)
        relative = abs(area_after - area_before) / max(area_before, 1e-15)
        max_shift = (
            config.max_shape_shift if config.max_shape_shift is not None else config.tolerance
        )
        reason = ""
        if after.equals_exact(before, 0):
            reason = "no eligible vertex was within tolerance"
        elif (
            after.is_empty
            or not after.is_valid
            or after.geom_type not in {"Polygon", "MultiPolygon"}
        ):
            reason = "candidate is not a valid polygon"
        elif shift > max_shift:
            reason = "shape shift exceeds configured limit"
        elif relative > config.max_relative_area_change:
            reason = "relative area change exceeds configured limit"
        else:
            for other_index, other in enumerate(all_geometries):
                if other_index == index:
                    continue
                overlap_before = before.intersection(other).area
                overlap_after = after.intersection(other).area
                if overlap_after - overlap_before > 1e-12:
                    reason = "candidate creates or increases an overlap"
                    break
        accepted = not reason
        final = after if accepted else before
        return BoundarySnapFeature(
            index,
            "repaired" if accepted else "unchanged",
            _wkt(before),
            _wkt(final),
            area_before,
            final.area,
            before.hausdorff_distance(final),
            tuple(sorted(neighbours)) if accepted else (),
            reason,
        )
