"""Legacy-style in-memory geometry execution adapter."""

from collections import Counter

import pyogrio  # type: ignore[import-untyped]

from geoqc.application.streaming.geometry import GeometryAuditResult, GeometryFinding
from geoqc.application.streaming.models import DatasetSource
from geoqc.infrastructure.gis.shapely_geometry_validator import ShapelyGeometryValidator


class GeoPandasGeometryEngine:
    """Load a safe-sized dataset in memory while preserving audit semantics."""

    def __init__(self, maximum_findings: int = 1_000) -> None:
        self._maximum_findings = maximum_findings

    def run(self, source: DatasetSource) -> GeometryAuditResult:
        frame = pyogrio.read_dataframe(source.path, layer=source.layer)
        validator = ShapelyGeometryValidator()
        counts: Counter[str] = Counter()
        findings: list[GeometryFinding] = []
        invalid_count = 0
        for index, geometry in enumerate(frame.geometry):
            issues: tuple[tuple[str, str], ...]
            if geometry is None:
                issues = (("empty_geometry", "Geometry is missing."),)
            else:
                result = validator.validate(geometry)
                issues = tuple(
                    (str(getattr(issue.issue_type, "value", issue.issue_type)), issue.message)
                    for issue in result.issues
                )
            if issues:
                invalid_count += 1
                counts.update(item[0] for item in issues)
                if len(findings) < self._maximum_findings:
                    findings.append(GeometryFinding(index, issues))
        return GeometryAuditResult(
            len(frame),
            invalid_count,
            dict(sorted(counts.items())),
            tuple(findings),
        )
