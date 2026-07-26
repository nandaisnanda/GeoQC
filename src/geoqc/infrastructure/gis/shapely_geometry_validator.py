"""Geometry validation implemented with Shapely topology predicates."""

from collections.abc import Iterable, Iterator, Sequence
from itertools import islice

from shapely import is_valid_reason
from shapely.geometry import (
    GeometryCollection,
    LinearRing,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.geometry.base import BaseGeometry

from geoqc.domain.models import (
    GeometryIssueType,
    GeometryValidationIssue,
    GeometryValidationResult,
)

Coordinate = tuple[float, ...]

_RING_ERROR_REASONS = (
    "ring self-intersection",
    "too few points in geometry component",
    "hole lies outside shell",
    "holes are nested",
    "nested shells",
    "disconnected interior",
)

_SELF_INTERSECTION_REASON = "self-intersection"
_MAX_DUPLICATE_LOCATIONS = 20


class ShapelyGeometryValidator:
    """Detect topology and vertex defects in a Shapely geometry."""

    def validate(self, geometry: BaseGeometry) -> GeometryValidationResult:
        """Validate one geometry and return all detectable issue categories."""
        if not isinstance(geometry, BaseGeometry):
            raise TypeError("geometry must be a Shapely BaseGeometry")

        issues: list[GeometryValidationIssue] = []
        if geometry.is_empty:
            issues.append(
                GeometryValidationIssue(
                    GeometryIssueType.EMPTY_GEOMETRY,
                    "Geometry is empty.",
                )
            )

        is_valid = geometry.is_valid
        reason = is_valid_reason(geometry) if not is_valid else None
        if reason is not None:
            issues.append(
                GeometryValidationIssue(
                    GeometryIssueType.INVALID_GEOMETRY,
                    f"Geometry is invalid: {reason}.",
                )
            )

        ring_reason, intersection_reason = self._polygon_issue_reasons(geometry)
        if ring_reason is not None:
            issues.append(
                GeometryValidationIssue(
                    GeometryIssueType.RING_ERROR,
                    f"Polygon ring error detected: {ring_reason}.",
                )
            )

        has_line_intersection = self._has_line_self_intersection(geometry)
        if intersection_reason is not None or has_line_intersection:
            detail = (
                intersection_reason if intersection_reason is not None else "linework is not simple"
            )
            issues.append(
                GeometryValidationIssue(
                    GeometryIssueType.SELF_INTERSECTION,
                    f"Self-intersection detected: {detail}.",
                )
            )

        duplicate_locations = tuple(
            islice(self._duplicate_locations(geometry), _MAX_DUPLICATE_LOCATIONS + 1)
        )
        if duplicate_locations:
            reported_locations = duplicate_locations[:_MAX_DUPLICATE_LOCATIONS]
            locations = ", ".join(reported_locations)
            if len(duplicate_locations) > _MAX_DUPLICATE_LOCATIONS:
                locations = f"{locations}, and additional locations"
            issues.append(
                GeometryValidationIssue(
                    GeometryIssueType.DUPLICATE_VERTEX,
                    f"Duplicate vertex detected in: {locations}.",
                )
            )

        return GeometryValidationResult(geometry.geom_type, tuple(issues))

    def _duplicate_locations(self, geometry: BaseGeometry) -> Iterator[str]:
        for path, coordinates, closed in self._coordinate_sequences(geometry):
            if self._has_duplicate(coordinates, closed=closed):
                yield path

    def _coordinate_sequences(
        self,
        geometry: BaseGeometry,
        path: str = "geometry",
    ) -> Iterator[tuple[str, Iterable[Sequence[float]], bool]]:
        pending: list[tuple[str, BaseGeometry]] = [(path, geometry)]
        while pending:
            current_path, current = pending.pop()
            if isinstance(current, Point):
                if not current.is_empty:
                    yield current_path, current.coords, False
            elif isinstance(current, LinearRing):
                yield current_path, current.coords, True
            elif isinstance(current, LineString):
                yield current_path, current.coords, current.is_closed
            elif isinstance(current, Polygon):
                if not current.is_empty:
                    yield f"{current_path}.exterior", current.exterior.coords, True
                    for index, ring in enumerate(current.interiors):
                        yield f"{current_path}.interiors[{index}]", ring.coords, True
            elif isinstance(current, MultiPoint):
                coordinates = (point.coords[0] for point in current.geoms if not point.is_empty)
                yield current_path, coordinates, False
            elif isinstance(current, (MultiLineString, MultiPolygon, GeometryCollection)):
                parts = current.geoms
                pending.extend(
                    (f"{current_path}.geoms[{index}]", parts[index])
                    for index in range(len(parts) - 1, -1, -1)
                )

    @staticmethod
    def _has_line_self_intersection(geometry: BaseGeometry) -> bool:
        lines: list[LineString] = []
        pending = [geometry]
        while pending:
            current = pending.pop()
            if isinstance(current, LineString):
                if current.is_valid:
                    lines.append(current)
            elif isinstance(current, MultiLineString):
                lines.extend(line for line in current.geoms if line.is_valid)
            elif isinstance(current, GeometryCollection):
                pending.extend(current.geoms)

        if not lines:
            return False
        if len(lines) == 1:
            return not lines[0].is_simple
        return not MultiLineString(lines).is_simple

    @staticmethod
    def _polygon_issue_reasons(
        geometry: BaseGeometry,
    ) -> tuple[str | None, str | None]:
        ring_reason: str | None = None
        intersection_reason: str | None = None
        pending = [geometry]
        while pending:
            current = pending.pop()
            if isinstance(current, (Polygon, MultiPolygon)) and not current.is_valid:
                reason = is_valid_reason(current)
                normalized_reason = reason.casefold()
                if ring_reason is None and any(
                    marker in normalized_reason for marker in _RING_ERROR_REASONS
                ):
                    ring_reason = reason
                if intersection_reason is None and _SELF_INTERSECTION_REASON in normalized_reason:
                    intersection_reason = reason
                if ring_reason is not None and intersection_reason is not None:
                    return ring_reason, intersection_reason
            if isinstance(current, (MultiPolygon, GeometryCollection)):
                pending.extend(current.geoms)
        return ring_reason, intersection_reason

    @staticmethod
    def _has_duplicate(coordinates: Iterable[Sequence[float]], *, closed: bool) -> bool:
        iterator = iter(coordinates)
        try:
            first = ShapelyGeometryValidator._coordinate(next(iterator))
        except StopIteration:
            return False

        seen = {first}
        try:
            previous = ShapelyGeometryValidator._coordinate(next(iterator))
        except StopIteration:
            return False

        vertex_count = 2
        for raw_coordinate in iterator:
            if previous in seen:
                return True
            seen.add(previous)
            previous = ShapelyGeometryValidator._coordinate(raw_coordinate)
            vertex_count += 1

        if closed and vertex_count > 2 and previous == first:
            return False
        return previous in seen

    @staticmethod
    def _coordinate(point: Sequence[float]) -> Coordinate:
        return tuple(float(value) for value in point)
