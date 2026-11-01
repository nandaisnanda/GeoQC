"""Impact summary: how much of a layer, in hectares or kilometres, carries errors."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]

from geoqc.domain.models import DatasetAuditResult
from geoqc.domain.models.topology import DatasetIssue, IssueGeometryKind
from geoqc.domain.rules import Severity

IMPACT_SKIPPED_MESSAGE = "Impact: skipped (CRS missing)"
_ERROR_LEVELS = frozenset({Severity.ERROR, Severity.CRITICAL})
_UNITS = {IssueGeometryKind.POLYGON: "ha", IssueGeometryKind.LINE: "km"}


@dataclass(frozen=True, slots=True)
class CodeImpact:
    code: str
    issue_count: int
    feature_count: int
    unit: str
    measure: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "issue_count": self.issue_count,
            "feature_count": self.feature_count,
            "unit": self.unit,
            "measure": self.measure,
        }


@dataclass(frozen=True, slots=True)
class LayerImpact:
    layer: str
    unit: str
    feature_count: int
    affected_feature_count: int
    total_measure: float | None
    affected_measure: float | None
    codes: tuple[CodeImpact, ...]

    @property
    def share_percent(self) -> float:
        if self.total_measure is None:
            total, part = float(self.feature_count), float(self.affected_feature_count)
        else:
            total, part = self.total_measure, self.affected_measure or 0.0
        return 100 * part / total if total else 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "layer": self.layer,
            "unit": self.unit,
            "feature_count": self.feature_count,
            "affected_feature_count": self.affected_feature_count,
            "total_measure": self.total_measure,
            "affected_measure": self.affected_measure,
            "share_percent": round(self.share_percent, 4),
            "codes": [code.to_dict() for code in self.codes],
        }


@dataclass(frozen=True, slots=True)
class ImpactSummary:
    status: str
    crs: str | None = None
    metric_crs: str | None = None
    note: str | None = None
    layers: tuple[LayerImpact, ...] = ()

    @property
    def skipped(self) -> bool:
        return self.status != "computed"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "crs": self.crs,
            "metric_crs": self.metric_crs,
            "note": self.note,
            "layers": [layer.to_dict() for layer in self.layers],
        }

    def cli_lines(self) -> list[str]:
        """At most six lines: one Impact line per layer, the CRS note, the top three codes."""
        if self.skipped:
            return [IMPACT_SKIPPED_MESSAGE]
        lines = []
        for layer in self.layers:
            if layer.total_measure is None:
                lines.append(
                    f"Impact: {layer.affected_feature_count} of {layer.feature_count} "
                    f"features ({format_share(layer.share_percent)}%) have errors"
                )
            else:
                lines.append(
                    f"Impact: {format_measure(layer.affected_measure or 0.0)} {layer.unit} of "
                    f"{format_measure(layer.total_measure)} {layer.unit} "
                    f"({format_share(layer.share_percent)}%) sits in features with errors"
                )
        if self.note:
            lines.append(f"  Note: {self.note}")
        codes = sorted(
            (code for layer in self.layers for code in layer.codes),
            key=lambda item: (item.measure is not None, item.measure or 0.0, item.issue_count),
            reverse=True,
        )
        for code in codes[:3]:
            measure = (
                "" if code.measure is None else f"{format_measure(code.measure)} {code.unit}, "
            )
            lines.append(
                f"  {code.code}: {measure}{code.issue_count} issue(s), "
                f"{code.feature_count} feature(s)"
            )
        return lines[:6]


def format_measure(value: float) -> str:
    """Two decimals, or four for small non-zero values so tiny datasets do not read 0.00."""
    return f"{value:.4f}" if 0 < abs(value) < 0.1 else f"{value:.2f}"


def format_share(value: float) -> str:
    """One decimal, but never round a partial share to 0.0 or 100.0."""
    if 0 < value < 0.05 or 99.95 <= value < 100:
        return f"{value:.2f}" if 0.005 <= value < 99.995 else f"{value:.4f}"
    return f"{value:.1f}"


def compute_impact(
    issues: Iterable[DatasetIssue], frame: gpd.GeoDataFrame, layer: str
) -> ImpactSummary:
    """Measure issue geometries and error-affected features in metric units.

    Info findings are ignored. A feature counts once however many issues touch it,
    including features named as ``related_feature_index`` (e.g. both sides of an overlap).
    """
    if frame.crs is None:
        return ImpactSummary(status="skipped_crs_missing")
    crs = frame.crs
    note = None
    if crs.is_geographic:
        metric = frame.estimate_utm_crs()
        note = f"geographic CRS {crs.to_string()}; measured in {metric.to_string()} (UTM estimate)"
    else:
        metric = crs
    metric_frame = frame.to_crs(metric) if metric != crs else frame
    geometry = metric_frame.geometry.make_valid()

    selected = [issue for issue in issues if issue.severity is not Severity.INFO]
    measures = _issue_measures(selected, crs, metric)
    by_code: dict[str, list[tuple[DatasetIssue, float | None]]] = {}
    for issue, measure in zip(selected, measures, strict=True):
        by_code.setdefault(issue.code, []).append((issue, measure))
    codes = tuple(_code_impact(code, items) for code, items in by_code.items())

    affected = sorted(
        {
            index
            for issue in selected
            if issue.severity in _ERROR_LEVELS
            for index in issue.feature_indices
            if 0 <= index < len(frame)
        }
    )
    unit = _layer_unit(geometry)
    if unit == "ha":
        values = geometry.area / 10_000
    elif unit == "km":
        values = geometry.length / 1_000
    else:
        values = None
    layer_impact = LayerImpact(
        layer=layer,
        unit=unit,
        feature_count=len(frame),
        affected_feature_count=len(affected),
        total_measure=None if values is None else float(values.sum()),
        affected_measure=None if values is None else float(values.iloc[affected].sum()),
        codes=codes,
    )
    return ImpactSummary(
        status="computed",
        crs=crs.to_string(),
        metric_crs=metric.to_string(),
        note=note,
        layers=(layer_impact,),
    )


def load_impact(result: DatasetAuditResult, source: Path, layer: str | None) -> ImpactSummary:
    """Read the audited layer again and compute its impact summary."""
    frame = gpd.read_file(source, layer=layer)
    return compute_impact(result.issues, frame, layer or source.stem)


def _issue_measures(issues: list[DatasetIssue], crs: object, metric: object) -> list[float | None]:
    if not issues:
        return []
    shapes = gpd.GeoSeries.from_wkt([issue.geometry_wkt for issue in issues], crs=crs)
    if metric != crs:
        shapes = shapes.to_crs(metric)
    shapes = shapes.make_valid()
    measures: list[float | None] = []
    for issue, shape in zip(issues, shapes, strict=True):
        if issue.geometry_kind is IssueGeometryKind.POLYGON:
            measures.append(shape.area / 10_000)
        elif issue.geometry_kind is IssueGeometryKind.LINE:
            measures.append(shape.length / 1_000)
        else:
            measures.append(None)
    return measures


def _code_impact(code: str, items: list[tuple[DatasetIssue, float | None]]) -> CodeImpact:
    kinds = {issue.geometry_kind for issue, _ in items}
    unit = _UNITS[kinds.pop()] if len(kinds) == 1 and kinds <= _UNITS.keys() else "count"
    features = {(issue.layer, index) for issue, _ in items for index in issue.feature_indices}
    measure = None if unit == "count" else float(sum(value or 0.0 for _, value in items))
    return CodeImpact(code, len(items), len(features), unit, measure)


def _layer_unit(geometry: gpd.GeoSeries) -> str:
    types = geometry[~geometry.is_empty & geometry.notna()].geom_type
    if types.str.contains("Polygon").any():
        return "ha"
    if types.str.contains("LineString").any():
        return "km"
    return "count"
