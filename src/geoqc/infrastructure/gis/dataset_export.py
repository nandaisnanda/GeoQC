"""Dataset export for the canonical dataset workflow."""

import json
from pathlib import Path
from uuid import uuid4

import geopandas as gpd  # type: ignore[import-untyped]
import pandas as pd

from geoqc.domain.models import (
    DatasetAuditResult,
    IssueGeometryKind,
)
from geoqc.domain.models.quality_workflow import AuditResultExporter
from geoqc.infrastructure.gis.quality_workflow import (
    issues_to_geodataframe,
)


class _ResultExporter(AuditResultExporter):
    def json(self, result: DatasetAuditResult, destination: Path, *, overwrite: bool) -> Path:
        return write_audit_report(result, destination, overwrite=overwrite)

    def html(self, result: DatasetAuditResult, destination: Path, *, overwrite: bool) -> Path:
        return write_audit_report(result, destination, overwrite=overwrite)

    def findings(self, result: DatasetAuditResult, destination: Path, *, overwrite: bool) -> Path:
        return write_issue_layers(result, destination, overwrite=overwrite)


def write_issue_layers(
    result: DatasetAuditResult,
    destination: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Atomically write point, line, and polygon findings to one GeoPackage."""
    path = Path(destination)
    if path.suffix.casefold() != ".gpkg":
        raise ValueError("issue dataset must use .gpkg")
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.{uuid4().hex}.tmp.gpkg")
    try:
        wrote = False
        for kind in IssueGeometryKind:
            frame = issues_to_geodataframe(result, kind)
            if frame.empty:
                continue
            frame.to_file(temporary, layer=f"geoqc_errors_{kind.value}", driver="GPKG")
            wrote = True
        if not wrote:
            empty = gpd.GeoDataFrame(
                {"status": pd.Series(dtype="str")},
                geometry=gpd.GeoSeries([], dtype="geometry", crs=result.crs_guard.crs),
            )
            empty.to_file(temporary, layer="geoqc_errors_point", driver="GPKG")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def write_audit_report(
    result: DatasetAuditResult,
    destination: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Write JSON or self-contained HTML directly from a unified audit result."""
    path = Path(destination)
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    if path.suffix.casefold() == ".json":
        _atomic_text(path, json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n")
        return path
    if path.suffix.casefold() == ".html":
        from geoqc import build_quality_report
        from geoqc.infrastructure.reporting import HtmlReportRenderer

        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            HtmlReportRenderer().write(build_quality_report(result), temporary)
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return path
    raise ValueError("audit report must use .json or .html")


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()
