"""Typer composition root for the GeoQC command-line interface."""

import json
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer

from geoqc import __version__
from geoqc.application.benchmarking import BenchmarkReport
from geoqc.application.parallel import ParallelBatchExecutor
from geoqc.application.parallel.scheduler import TaskScheduler
from geoqc.application.services import BatchProcessor
from geoqc.domain.models.spatial_intelligence import RoadNetworkRepairConfig
from geoqc.infrastructure.gis.parallel_audit import (
    DatasetAudit,
    DatasetAuditWorker,
    audit_dataset,
)
from geoqc.infrastructure.gis.road_dataset_repair import RoadDatasetRepairer
from geoqc.infrastructure.reporting import BenchmarkFormat, write_benchmark_report
from geoqc.interfaces.cli.progress import ParallelConsoleProgress

app: typer.Typer = typer.Typer(
    name="geoqc",
    help="GeoQC GIS quality-control toolkit.",
    invoke_without_command=True,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        is_eager=True,
        help="Show the installed GeoQC version and exit.",
    ),
) -> None:
    """Run the GeoQC command-line interface."""
    if version:
        typer.echo(f"GeoQC {__version__}")
        raise typer.Exit()


@app.command()
def audit(
    inputs: Annotated[
        list[Path],
        typer.Argument(help="Dataset files or folders to audit."),
    ],
    recursive: Annotated[
        bool,
        typer.Option("--recursive", "-r", help="Discover datasets recursively."),
    ] = False,
    benchmark: Annotated[
        bool,
        typer.Option("--benchmark/--no-benchmark", help="Collect process-local audit metrics."),
    ] = False,
    benchmark_output: Annotated[
        Path,
        typer.Option(help="Benchmark report path; suffix selects the format."),
    ] = Path("geoqc-benchmark.html"),
    benchmark_format: Annotated[
        BenchmarkFormat | None,
        typer.Option(help="Override benchmark output format: html, json, or markdown."),
    ] = None,
    workers: Annotated[
        int | None,
        typer.Option(min=1, help="Maximum worker processes."),
    ] = None,
    chunk_size: Annotated[
        int,
        typer.Option(min=1, help="Maximum features per streaming chunk."),
    ] = 16_384,
) -> None:
    """Audit independent datasets with automatic safe multiprocessing."""
    discovery = BatchProcessor[DatasetAudit](audit_dataset)
    try:
        sources = discovery.discover(inputs, recursive=recursive)
    except (FileNotFoundError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error

    scheduler = TaskScheduler()
    worker_count = scheduler.worker_count(len(sources), requested_workers=workers)
    worker = DatasetAuditWorker(
        benchmark_enabled=benchmark,
        chunk_size=chunk_size,
        worker_count=worker_count,
    )
    result = ParallelBatchExecutor(scheduler).run(
        sources,
        worker,
        requested_workers=workers,
        progress=ParallelConsoleProgress(),
    )
    for item in result.items:
        if item.value is None:
            typer.echo(f"FAILED {item.source}: {item.error}")
            continue
        audit_result = item.value.result
        typer.echo(
            f"OK {item.source}: engine={item.value.decision.engine} "
            f"features={audit_result.feature_count} "
            f"invalid={audit_result.invalid_feature_count}"
        )
    typer.echo(
        f"Audit complete: total={result.total} succeeded={result.succeeded} failed={result.failed}"
    )
    if benchmark:
        report = BenchmarkReport(
            tuple(
                item.value.benchmark
                for item in result.items
                if item.value is not None and item.value.benchmark is not None
            )
        )
        try:
            write_benchmark_report(report, benchmark_output, benchmark_format)
        except (OSError, ValueError) as error:
            typer.echo(f"Error writing benchmark report: {error}", err=True)
            raise typer.Exit(code=2) from error
        typer.echo(f"Benchmark report: {benchmark_output}")
    if not result.is_successful:
        raise typer.Exit(code=1)


@app.command("repair-roads")
def repair_roads(
    source: Annotated[Path, typer.Argument(help="Input road vector dataset.")],
    output: Annotated[Path, typer.Argument(help="New output GeoPackage path.")],
    layer: Annotated[
        str | None,
        typer.Option(help="Input layer name; required for multi-layer GeoPackages."),
    ] = None,
    output_layer: Annotated[
        str,
        typer.Option(help="Layer name to create in the output GeoPackage."),
    ] = "repaired_roads",
    snap_tolerance: Annotated[
        float,
        typer.Option(min=0, help="Maximum endpoint snap distance in CRS units."),
    ] = 0.0,
    minimum_segment_length: Annotated[
        float,
        typer.Option(min=1e-15, help="Discard noded segments shorter than this value."),
    ] = 1e-9,
    report: Annotated[
        Path | None,
        typer.Option(help="Optional JSON summary path."),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Replace an existing output GeoPackage."),
    ] = False,
    allow_geographic: Annotated[
        bool,
        typer.Option(
            "--allow-geographic",
            help="Allow a nonzero snap tolerance in geographic CRS degrees.",
        ),
    ] = False,
    max_features: Annotated[
        int,
        typer.Option(min=1, help="In-memory safety limit for input features."),
    ] = 500_000,
) -> None:
    """Snap endpoint gaps and fully node a road network without changing the source."""
    try:
        config = RoadNetworkRepairConfig(
            snap_tolerance=snap_tolerance,
            minimum_segment_length=minimum_segment_length,
        )
        result = RoadDatasetRepairer().repair(
            source,
            output,
            config,
            layer=layer,
            output_layer=output_layer,
            overwrite=overwrite,
            allow_geographic=allow_geographic,
            max_features=max_features,
        )
        if report is not None:
            _write_json_report(report, result.to_dict(), protected={source, output})
    except (FileNotFoundError, OSError, TypeError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error

    typer.echo(
        f"Repair complete: input={result.input_feature_count} "
        f"parts={result.input_part_count} snapped={result.snapped_endpoint_count} "
        f"segments={result.output_segment_count}"
    )
    typer.echo(f"Output: {result.output} layer={result.output_layer}")
    if report is not None:
        typer.echo(f"Report: {report.resolve()}")


def _write_json_report(path: Path, payload: dict[str, object], *, protected: set[Path]) -> None:
    destination = path.resolve()
    if destination in {item.resolve() for item in protected}:
        raise ValueError("Report path must differ from input and output dataset paths.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def run() -> None:
    """Execute the Typer application from the console-script entry point."""
    app()
