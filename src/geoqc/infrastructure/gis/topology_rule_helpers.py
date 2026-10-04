"""Shared geometry helpers for advanced topology rules."""

from collections.abc import Mapping, Sequence
from math import acos, degrees, hypot

import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from geoqc.domain.models.quality_workflow import (
    DatasetIssue,
    IssueGeometryKind,
    RepairRisk,
    TopologyRule,
)

AttributeValue = str | int | float | bool | None


def _line_records(source: Sequence[BaseGeometry]) -> list[tuple[int, LineString]]:
    records: list[tuple[int, LineString]] = []
    for owner, geometry in enumerate(source):
        if isinstance(geometry, LineString):
            records.append((owner, geometry))
        elif geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
            records.extend(
                (owner, part)
                for part in shapely.get_parts(geometry)
                if isinstance(part, LineString) and not part.is_empty
            )
    return records


def _coordinate_sequences(
    source: Sequence[BaseGeometry],
) -> list[tuple[int, list[tuple[float, float]], bool]]:
    output: list[tuple[int, list[tuple[float, float]], bool]] = []
    pending = list(enumerate(source))
    while pending:
        owner, geometry = pending.pop(0)
        if isinstance(geometry, LineString):
            coordinates = [(float(x), float(y)) for x, y, *_ in geometry.coords]
            output.append((owner, coordinates, geometry.is_closed))
        elif isinstance(geometry, Polygon):
            exterior = [(float(x), float(y)) for x, y, *_ in geometry.exterior.coords]
            output.append((owner, exterior, True))
            output.extend(
                (owner, [(float(x), float(y)) for x, y, *_ in ring.coords], True)
                for ring in geometry.interiors
            )
        elif geometry.geom_type.startswith("Multi") or geometry.geom_type == "GeometryCollection":
            pending[0:0] = [(owner, part) for part in shapely.get_parts(geometry)]
    return output


def _points(geometry: BaseGeometry) -> list[Point]:
    if isinstance(geometry, Point):
        return [geometry]
    if geometry.geom_type in {"MultiPoint", "GeometryCollection"}:
        return [item for item in shapely.get_parts(geometry) if isinstance(item, Point)]
    return []


def _angle(
    before: tuple[float, float], vertex: tuple[float, float], after: tuple[float, float]
) -> float | None:
    first = (before[0] - vertex[0], before[1] - vertex[1])
    second = (after[0] - vertex[0], after[1] - vertex[1])
    norm = hypot(*first) * hypot(*second)
    if norm == 0:
        return None
    cosine = max(-1.0, min(1.0, (first[0] * second[0] + first[1] * second[1]) / norm))
    return degrees(acos(cosine))


def _issue(
    rule: TopologyRule,
    feature_index: int,
    geometry: BaseGeometry,
    title: str,
    message: str,
    recommendation: str,
    *,
    related: int | None = None,
    metadata: Mapping[str, str | int | float | bool | None] | None = None,
) -> DatasetIssue:
    return DatasetIssue(
        code=f"TOP-{rule.rule_type.value.upper().replace('_', '-')}",
        issue_type=rule.rule_type.value,
        title=title,
        message=message,
        severity=rule.severity,
        category="topology",
        recommendation=recommendation,
        repair_risk=RepairRisk.REVIEW,
        geometry_kind=_kind(geometry),
        geometry_wkt=str(shapely.to_wkt(geometry, rounding_precision=-1)),
        layer=rule.layer,
        feature_index=feature_index,
        related_feature_index=related,
        metadata=metadata or {},
    )


def _kind(geometry: BaseGeometry) -> IssueGeometryKind:
    dimension = int(shapely.get_dimensions(geometry))
    if dimension >= 2:
        return IssueGeometryKind.POLYGON
    if dimension == 1:
        return IssueGeometryKind.LINE
    return IssueGeometryKind.POINT


def _unique(findings: Sequence[DatasetIssue]) -> list[DatasetIssue]:
    return list({item.fingerprint: item for item in findings}.values())


def _metadata_value(value: AttributeValue) -> str | int | float | bool | None:
    return value
