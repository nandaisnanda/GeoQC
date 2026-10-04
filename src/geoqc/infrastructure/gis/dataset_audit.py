"""Composition root for the public dataset-level audit workflow."""

from collections import Counter
from collections.abc import Iterable
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import pyogrio  # type: ignore[import-untyped]

from geoqc.application.engine_selection import EngineDecision
from geoqc.application.streaming.geometry import GeometryAuditResult
from geoqc.application.streaming.models import DatasetSource
from geoqc.domain.models import (
    AttributeIssueType,
    AttributeSchema,
    AuditCheckResult,
    AuditDatasetMetadata,
    AuditIssue,
    CheckStatus,
    DatasetAuditReport,
    DatasetAuditResult,
)
from geoqc.domain.rules import Severity
from geoqc.infrastructure.gis.automatic_geometry_engine import AutomaticGeometryEngine
from geoqc.infrastructure.gis.pandas_attribute_scanner import PandasAttributeScanner
from geoqc.infrastructure.gis.quality_workflow import assess_crs
from geoqc.infrastructure.gis.streaming import default_reader_registry

_CHECK_NAMES = ("geometry", "crs", "attributes", "topology", "spatial")
_GEOMETRY_RECOMMENDATIONS = {
    "duplicate_vertex": "Remove the duplicate vertex and validate the geometry again.",
    "empty_geometry": "Restore the missing geometry or remove the feature.",
    "invalid_geometry": "Repair the geometry and validate it again.",
    "ring_error": "Repair the polygon ring and validate the geometry again.",
    "self_intersection": "Repair the self-intersection and validate the geometry again.",
}
_ATTRIBUTE_RECOMMENDATIONS = {
    AttributeIssueType.DUPLICATE_ID: "Assign a unique, non-null identifier to every feature.",
    AttributeIssueType.INVALID_DATA_TYPE: "Convert the reported values to the schema type.",
    AttributeIssueType.MISSING_COLUMN: "Add the required column or update the supplied schema.",
    AttributeIssueType.NULL_VALUE: "Populate the required values or make the column nullable.",
    AttributeIssueType.SCHEMA_DRIFT: "Reconcile the dataset columns with the supplied schema.",
}


def _audit_dataset_with_geometry(
    source: str | Path,
    *,
    layer: str | None = None,
    schema: AttributeSchema | None = None,
    checks: str | Iterable[str] = "all",
    chunk_size: int = 16_384,
) -> tuple[DatasetAuditResult, GeometryAuditResult, EngineDecision]:
    """Return the public report plus legacy execution details for CLI adapters."""
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_file():
        raise ValueError(f"dataset must be a file: {path}")
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    selected = _normalize_checks(checks)
    dataset_source = DatasetSource(path=path, layer=layer)
    reader = default_reader_registry().resolve(dataset_source)
    metadata = reader.inspect(dataset_source)
    geometry_result, decision = AutomaticGeometryEngine(reader, chunk_size=chunk_size).run(
        dataset_source
    )
    report_metadata = AuditDatasetMetadata(
        path=str(path.resolve()),
        layer=metadata.layer,
        driver=metadata.driver,
        crs=metadata.crs,
        feature_count=geometry_result.feature_count,
        geometry_column=metadata.geometry_column,
        size_bytes=decision.profile.size_bytes,
        engine=decision.engine,
    )
    results = (
        _geometry_check(geometry_result) if "geometry" in selected else _not_selected("geometry"),
        _crs_check(metadata.crs) if "crs" in selected else _not_selected("crs"),
        _attribute_check(path, metadata.layer, schema)
        if "attributes" in selected
        else _not_selected("attributes"),
        _configuration_check(
            "topology",
            selected,
            "No topology rules were supplied. Configure a QualityProfile for topology checks.",
            metadata.crs,
        ),
        _configuration_check(
            "spatial",
            selected,
            "No reference layer or spatial relationship was supplied.",
            metadata.crs,
        ),
    )
    report = DatasetAuditReport(report_metadata, results)
    if not isinstance(report, DatasetAuditResult):
        raise TypeError("DatasetAuditReport compatibility adapter returned an invalid result")
    return report, geometry_result, decision


def _normalize_checks(checks: str | Iterable[str]) -> frozenset[str]:
    values: tuple[str, ...]
    if isinstance(checks, str):
        values = _CHECK_NAMES if checks.casefold() == "all" else (checks,)
    else:
        values = tuple(checks)
    normalized = frozenset(str(value).strip().casefold() for value in values)
    unknown = normalized.difference(_CHECK_NAMES)
    if not normalized or unknown:
        detail = ", ".join(sorted(unknown)) if unknown else "no checks"
        raise ValueError(f"unknown audit checks: {detail}")
    return normalized


def _geometry_check(result: GeometryAuditResult) -> AuditCheckResult:
    issues = tuple(
        AuditIssue(
            code=f"GEO-{issue_type.upper()}",
            message=message,
            severity=Severity.WARNING if issue_type == "duplicate_vertex" else Severity.ERROR,
            recommendation=_GEOMETRY_RECOMMENDATIONS.get(
                issue_type, "Review and repair the geometry, then run the audit again."
            ),
            feature_indices=(finding.feature_index,),
        )
        for finding in result.findings
        for issue_type, message in finding.issues
    )
    return AuditCheckResult(
        "geometry",
        CheckStatus.FAILED if result.invalid_feature_count else CheckStatus.PASSED,
        issues,
        (
            f"{result.invalid_feature_count} invalid feature(s); "
            f"issue counts: {dict(sorted(result.issue_counts.items()))}."
            if result.invalid_feature_count
            else None
        ),
        {f"GEO-{name.upper()}": count for name, count in result.issue_counts.items()},
    )


def _crs_check(crs: str | None) -> AuditCheckResult:
    result = assess_crs(crs)
    if result.status.value == "safe":
        return AuditCheckResult("crs", CheckStatus.PASSED)
    recommendation = (
        f"Reproject to {result.suggested_projected_crs} before distance or area checks."
        if result.suggested_projected_crs
        else "Define a valid projected CRS before running distance or area checks."
    )
    return AuditCheckResult(
        "crs",
        CheckStatus.FAILED,
        (
            AuditIssue(
                code="CRS-UNSAFE-UNITS" if result.uses_angular_units else "CRS-MISSING",
                message=result.message,
                severity=Severity.WARNING if result.uses_angular_units else Severity.ERROR,
                recommendation=recommendation,
            ),
        ),
    )


def _attribute_check(
    path: Path, layer: str | None, schema: AttributeSchema | None
) -> AuditCheckResult:
    if schema is None:
        return AuditCheckResult(
            "attributes",
            CheckStatus.SKIPPED,
            reason="No attribute schema was supplied; pass schema=AttributeSchema(...).",
        )
    try:
        if path.suffix.casefold() == ".parquet":
            frame = gpd.read_parquet(path)
        else:
            frame = pyogrio.read_dataframe(path, layer=layer, read_geometry=False)
        result = PandasAttributeScanner().scan(frame, schema)
    except Exception as error:
        return AuditCheckResult(
            "attributes",
            CheckStatus.ERROR,
            reason=f"Attribute/schema scan failed: {type(error).__name__}: {error}",
        )
    issues = tuple(
        AuditIssue(
            code=f"ATTR-{issue.issue_type.value.upper()}",
            message=issue.message,
            severity=Severity.ERROR,
            recommendation=_ATTRIBUTE_RECOMMENDATIONS[issue.issue_type],
            feature_indices=issue.row_positions,
        )
        for issue in result.issues
    )
    return AuditCheckResult(
        "attributes",
        CheckStatus.FAILED if issues else CheckStatus.PASSED,
        issues,
        counts=Counter(issue.code for issue in issues),
    )


def _configuration_check(
    name: str, selected: frozenset[str], reason: str, crs: str | None
) -> AuditCheckResult:
    if name not in selected:
        return _not_selected(name)
    if not crs:
        reason = (
            "Dataset CRS is missing. Define a projected CRS and configure the required "
            f"{name} rules before running this check."
        )
    return AuditCheckResult(name, CheckStatus.SKIPPED, reason=reason)


def _not_selected(name: str) -> AuditCheckResult:
    return AuditCheckResult(
        name,
        CheckStatus.SKIPPED,
        reason="Check was not selected by the checks argument.",
    )
