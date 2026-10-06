"""Delivery commands: parse, compose existing services, and render stable outcomes."""

import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer
from pyogrio.errors import DataSourceError  # type: ignore[import-untyped]

from geoqc.application.services import (
    AxisOrderDetector,
    BatchProcessor,
    CrsConsistencyScanner,
    DatumShiftDetector,
)
from geoqc.domain.exceptions import GeoQCError
from geoqc.domain.models import CoordinateBounds, DatasetSource, GeographicBounds
from geoqc.infrastructure.gis.dataset_audit import audit_dataset
from geoqc.infrastructure.gis.pyogrio_crs_reader import PyogrioCrsMetadataReader
from geoqc.infrastructure.gis.pyproj_datum_inspector import PyprojDatumTransformationInspector

app = typer.Typer()
JsonOption = Annotated[bool, typer.Option("--json", help="Emit deterministic JSON.")]
BoundsOption = Annotated[tuple[float, float, float, float], typer.Option("--bounds")]
INVALID_INPUT = (OSError, ValueError, GeoQCError, DataSourceError)


def execute(action: Callable[[], tuple[dict[str, object], int]], as_json: bool) -> None:
    """Map adapter failures at the outermost command boundary, without tracebacks."""
    try:
        payload, code = action()
    except INVALID_INPUT as error:
        payload, code = {"error": str(error), "status": "invalid_input"}, 2
    except Exception:
        # This is the process boundary: unexpected service failures must exit 3.
        payload, code = {"error": "Unexpected internal failure.", "status": "internal_error"}, 3
    if as_json:
        typer.echo(json.dumps(payload, sort_keys=True, allow_nan=False))
    else:
        for key, value in sorted(payload.items()):
            typer.echo(f"{key}: {json.dumps(value, sort_keys=True, ensure_ascii=False)}")
    raise typer.Exit(code)


@app.command("crs-scan")
def crs_scan(
    inputs: Annotated[list[Path], typer.Argument()],
    layer: str | None = None,
    json_output: JsonOption = False,
) -> None:
    """Scan dataset CRS consistency against the first declared CRS."""

    def action() -> tuple[dict[str, object], int]:
        result = CrsConsistencyScanner(PyogrioCrsMetadataReader()).scan(
            DatasetSource(str(path), layer) for path in inputs
        )
        code = (
            2
            if any(item.status.value == "error" for item in result.datasets)
            else int(not result.is_consistent)
        )
        return asdict(result), code

    execute(action, json_output)


@app.command("axis-order")
def axis_order(bounds: BoundsOption, json_output: JsonOption = False) -> None:
    """Detect swapped geographic axes from MIN_X MIN_Y MAX_X MAX_Y."""

    def action() -> tuple[dict[str, object], int]:
        result = AxisOrderDetector().detect(CoordinateBounds(*bounds))
        return asdict(result), int(result.status.value != "correct")

    execute(action, json_output)


@app.command("datum-shift")
def datum_shift(
    source_crs: str,
    target_crs: str,
    bounds: BoundsOption,
    threshold_m: Annotated[float, typer.Option(min=0.000001)] = 5.0,
    grid_size: Annotated[int, typer.Option(min=2, max=25)] = 3,
    json_output: JsonOption = False,
) -> None:
    """Inspect datum shift over WEST SOUTH EAST NORTH geographic bounds."""

    def action() -> tuple[dict[str, object], int]:
        result = DatumShiftDetector(PyprojDatumTransformationInspector()).detect(
            source_crs,
            target_crs,
            GeographicBounds(*bounds),
            threshold_m=threshold_m,
            grid_size=grid_size,
        )
        code = int(result.status.value != "normal" or result.quality.value != "reliable")
        return asdict(result), code

    execute(action, json_output)


@app.command("batch")
def batch(
    inputs: Annotated[list[Path], typer.Argument()],
    recursive: bool = False,
    json_output: JsonOption = False,
) -> None:
    """Audit every discovered dataset, preserving outcomes after partial failure."""

    def audit(path: Path) -> tuple[dict[str, object], int]:
        try:
            result = audit_dataset(path)
        except INVALID_INPUT as error:
            return {"error": str(error), "status": "invalid_input"}, 2
        return result.to_dict(), int(not result.passes())

    def action() -> tuple[dict[str, object], int]:
        result = BatchProcessor(audit).process(inputs, recursive=recursive)
        if not result.items:
            raise ValueError("No supported datasets found.")
        items: list[dict[str, object]] = []
        code = 0
        for item in result.items:
            payload, item_code = (
                item.value
                if item.value is not None
                else ({"status": "internal_error", "error": "Unexpected internal failure."}, 3)
            )
            message = (
                "Audit completed."
                if item_code in {0, 1}
                else str(payload.get("error", "Dataset processing failed."))
            )
            items.append(
                {
                    "source": item.source,
                    "exit_code": item_code,
                    "message": message,
                    "result": payload,
                }
            )
            code = max(code, item_code)
        return {"items": items, "total": result.total}, code

    execute(action, json_output)


@app.command("html-report")
def html_report(
    source: Path,
    destination: Path,
    layer: str | None = None,
    overwrite: bool = False,
    json_output: JsonOption = False,
) -> None:
    """Audit a dataset and atomically create a self-contained HTML report."""

    def action() -> tuple[dict[str, object], int]:
        if destination.suffix.casefold() != ".html":
            raise ValueError("HTML report destination must use .html")
        result = audit_dataset(source, layer=layer)
        result.to_html(destination, overwrite=overwrite)
        passed = result.passes()
        return {
            "report": str(destination),
            "status": result.status.value,
            "quality_gate": "passed" if passed else "failed",
        }, int(not passed)

    execute(action, json_output)
