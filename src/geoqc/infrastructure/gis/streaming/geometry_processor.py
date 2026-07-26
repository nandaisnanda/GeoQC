"""Arrow-WKB geometry processor adapter for the streaming engine."""

from collections import Counter
from typing import Protocol

import pyarrow as pa  # type: ignore[import-untyped]
import shapely
from shapely.geometry.base import BaseGeometry

from geoqc.application.streaming.geometry import GeometryChunkResult, GeometryFinding
from geoqc.application.streaming.models import DatasetMetadata, FeatureChunk
from geoqc.domain.models.geometry_validation import GeometryValidationResult


class GeometryValidator(Protocol):
    def validate(self, geometry: BaseGeometry) -> GeometryValidationResult: ...


class GeometryChunkProcessor:
    """Validate WKB geometries from one Arrow batch."""

    def __init__(self, validator: GeometryValidator) -> None:
        self._validator = validator

    def process(self, chunk: FeatureChunk, metadata: DatasetMetadata) -> GeometryChunkResult:
        batch = chunk.features[1] if isinstance(chunk.features, tuple) else chunk.features
        if not isinstance(batch, pa.RecordBatch):
            raise TypeError("GeometryChunkProcessor expects an Arrow RecordBatch")
        column_name = metadata.geometry_column
        if isinstance(chunk.features, tuple):
            declared = chunk.features[0]
            if isinstance(declared, str) and declared in batch.schema.names:
                column_name = declared
        if column_name not in batch.schema.names and "wkb_geometry" in batch.schema.names:
            column_name = "wkb_geometry"
        if column_name not in batch.schema.names:
            raise ValueError(f"Geometry column {column_name!r} is missing from the chunk")
        values = batch.column(batch.schema.get_field_index(column_name)).to_pylist()

        counts: Counter[str] = Counter()
        findings: list[GeometryFinding] = []
        for local_index, wkb in enumerate(values):
            geometry = shapely.from_wkb(wkb) if wkb is not None else None
            issues = self._issues(geometry)
            if issues:
                counts.update(issue_type for issue_type, _message in issues)
                findings.append(GeometryFinding(chunk.offset + local_index, tuple(issues)))
        return GeometryChunkResult(len(values), len(findings), counts, tuple(findings))

    def _issues(self, geometry: BaseGeometry | None) -> list[tuple[str, str]]:
        if not isinstance(geometry, BaseGeometry):
            return [("empty_geometry", "Geometry is missing.")]
        result = self._validator.validate(geometry)
        return [
            (str(getattr(issue.issue_type, "value", issue.issue_type)), issue.message)
            for issue in result.issues
        ]
