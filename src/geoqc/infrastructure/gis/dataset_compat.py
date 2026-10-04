"""Dataset compat for the canonical dataset workflow."""

import warnings
from pathlib import Path

from geoqc.domain.models import (
    DatasetAuditResult,
    QualityPreset,
    QualityProfile,
    WorkflowArtifacts,
)
from geoqc.infrastructure.gis.dataset_audit import audit_dataset


def audit_file(
    source: str | Path,
    *,
    layer: str | None = None,
    profile: QualityProfile | None = None,
    preset: QualityPreset | str | None = None,
) -> DatasetAuditResult:
    """Deprecated alias for :func:`audit_dataset`."""
    warnings.warn(
        "audit_file() is deprecated; use geoqc.audit_dataset() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return audit_dataset(source, layer=layer, profile=profile, preset=preset)


def run_quality_workflow(
    source: str | Path,
    *,
    profile: QualityProfile,
    layer: str | None = None,
    issue_output: str | Path | None = None,
    report_output: str | Path | None = None,
    overwrite: bool = False,
) -> WorkflowArtifacts:
    """Deprecated orchestration wrapper around the canonical result methods."""
    warnings.warn(
        "run_quality_workflow() is deprecated; call geoqc.audit_dataset() and the "
        "result export methods instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    result = audit_dataset(source, layer=layer, profile=profile)
    if issue_output:
        result.write_findings(issue_output, overwrite=overwrite)
    if report_output:
        suffix = Path(report_output).suffix.casefold()
        if suffix == ".json":
            result.to_json(report_output, overwrite=overwrite)
        else:
            result.to_html(report_output, overwrite=overwrite)
    return WorkflowArtifacts(
        result=result,
        issue_dataset=str(Path(issue_output).resolve()) if issue_output else None,
        report=str(Path(report_output).resolve()) if report_output else None,
    )
