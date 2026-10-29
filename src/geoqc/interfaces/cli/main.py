"""Typer composition root for the GeoQC command-line interface."""

import json
import warnings
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer
from pyogrio import list_layers  # type: ignore[import-untyped]
from pyogrio.errors import DataSourceError  # type: ignore[import-untyped]

from geoqc import (
    CheckStatus,
    QualityGatePolicy,
    QualityPreset,
    QualityProfile,
    __version__,
    load_quality_profile,
    write_audit_report,
    write_issue_layers,
)
from geoqc import (
    audit_dataset as run_dataset_audit,
)
from geoqc.application.benchmarking import BenchmarkReport
from geoqc.application.parallel import ParallelBatchExecutor
from geoqc.application.parallel.scheduler import TaskScheduler
from geoqc.application.services import BatchProcessor
from geoqc.domain.models import DatasetAuditResult
from geoqc.domain.models.spatial_intelligence import RoadNetworkRepairConfig
from geoqc.domain.rules import Severity
from geoqc.infrastructure.gis.parallel_audit import (
    DatasetAudit,
    DatasetAuditWorker,
    audit_dataset_worker,
)
from geoqc.infrastructure.gis.road_dataset_repair import RoadDatasetRepairer
from geoqc.infrastructure.reporting import BenchmarkFormat, write_benchmark_report
from geoqc.interfaces.cli.delivery import app as delivery_app
from geoqc.interfaces.cli.progress import ParallelConsoleProgress

app: typer.Typer = typer.Typer(
    name="geoqc",
    help="GeoQC GIS quality-control toolkit.",
    invoke_without_command=True,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


app.add_typer(delivery_app)

AUDIT_SUFFIXES = (".fgb", ".geojson", ".gpkg", ".parquet", ".shp")
_SHAPEFILE_SIDECARS = frozenset(
    {".cpg", ".dbf", ".prj", ".qix", ".qmd", ".sbn", ".sbx", ".shx", ".xml"}
)


def _skipped_files(inputs: list[Path], sources: tuple[Path, ...], recursive: bool) -> list[str]:
    """List folder files that discovery ignored, without shapefile sidecars."""
    kept = set(sources)
    shapefiles = {
        (item.parent, item.stem.casefold()) for item in sources if item.suffix.casefold() == ".shp"
    }
    skipped: list[str] = []
    for folder in inputs:
        if not folder.is_dir():
            continue
        candidates = folder.rglob("*") if recursive else folder.glob("*")
        for candidate in candidates:
            if not candidate.is_file() or candidate.resolve() in kept:
                continue
            resolved = candidate.resolve()
            if (
                candidate.suffix.casefold() in _SHAPEFILE_SIDECARS
                and (resolved.parent, resolved.stem.casefold()) in shapefiles
            ):
                continue
            skipped.append(candidate.relative_to(folder).as_posix())
    return sorted(skipped, key=str.casefold)


def _echo_skipped(skipped: list[str]) -> None:
    if skipped:
        typer.echo(f"Skipped {len(skipped)} unsupported file(s): {', '.join(skipped)}")


def _echo_audit_item(label: str | Path, engine: str, audit_result: DatasetAuditResult) -> bool:
    """Print one audit result and return whether it passed the quality gate."""
    invalid_count = len([issue for issue in audit_result.issues if issue.category == "geometry"])
    report_suffix = f" status={audit_result.status.value} issues={audit_result.issue_count}"
    quality_passed = (
        audit_result.status not in {CheckStatus.FAILED, CheckStatus.ERROR} and audit_result.passes()
    )
    typer.echo(
        f"PROCESSED {label}: engine={engine} "
        f"features={audit_result.feature_count} "
        f"invalid={invalid_count}{report_suffix}"
    )
    typer.echo(f"QUALITY {'PASS' if quality_passed else 'FAIL'} {label}")
    return quality_passed


def _gpkg_layers(source: Path) -> list[str]:
    """Return GeoPackage layer names, or an empty list for other inputs."""
    if source.suffix.casefold() != ".gpkg" or not source.is_file():
        return []
    return [str(item[0]) for item in list_layers(source)]


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
    profile_path: Annotated[
        Path | None,
        typer.Option("--profile", help="JSON/YAML profile or a built-in profile name."),
    ] = None,
    layer: Annotated[
        str | None,
        typer.Option(help="Layer name for a single multi-layer dataset."),
    ] = None,
    report: Annotated[
        Path | None,
        typer.Option("--report", help="Write the audit result as HTML."),
    ] = None,
    json_output: Annotated[
        Path | None,
        typer.Option("--json", help="Write the audit result as deterministic JSON."),
    ] = None,
    findings: Annotated[
        Path | None,
        typer.Option("--findings", help="Write findings as a GeoPackage."),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Replace requested output files."),
    ] = False,
) -> None:
    """Audit independent datasets with automatic safe multiprocessing."""
    discovery = BatchProcessor[DatasetAudit](
        audit_dataset_worker, supported_suffixes=AUDIT_SUFFIXES
    )
    try:
        sources = discovery.discover(inputs, recursive=recursive)
    except (FileNotFoundError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error
    skipped = _skipped_files(inputs, sources, recursive)

    outputs_requested = any(item is not None for item in (report, json_output, findings))
    if (outputs_requested or layer is not None) and len(sources) != 1:
        typer.echo(
            "Error: report, json, findings, and layer options require one dataset.", err=True
        )
        raise typer.Exit(code=2)
    try:
        profile = load_quality_profile(profile_path) if profile_path is not None else None
    except (FileNotFoundError, OSError, TypeError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error

    if len(sources) == 1 and (outputs_requested or profile is not None or layer is not None):
        try:
            quality_result = run_dataset_audit(sources[0], layer=layer, profile=profile)
            if report is not None:
                quality_result.to_html(report, overwrite=overwrite)
            if json_output is not None:
                quality_result.to_json(json_output, overwrite=overwrite)
            if findings is not None:
                quality_result.write_findings(findings, overwrite=overwrite)
        except (
            DataSourceError,
            FileExistsError,
            FileNotFoundError,
            OSError,
            TypeError,
            ValueError,
        ) as error:
            typer.echo(f"Error: {error}", err=True)
            raise typer.Exit(code=2) from error
        passed = quality_result.passes(profile.gate if profile is not None else None)
        typer.echo(
            f"PROCESSED {sources[0]}: features={quality_result.feature_count} "
            f"issues={len(quality_result.issues)} score={quality_result.quality_score:.2f}"
        )
        typer.echo(f"QUALITY {'PASS' if passed else 'FAIL'}")
        _echo_skipped(skipped)
        if not passed:
            raise typer.Exit(code=1)
        return

    # The worker reads one layer per path, so multi-layer GeoPackages are
    # audited layer by layer here instead of in the process pool.
    layered: dict[Path, list[str]] = {}
    for source in sources:
        try:
            layer_names = _gpkg_layers(source)
        except DataSourceError:
            continue
        if len(layer_names) > 1:
            layered[source] = layer_names
    pool_sources = tuple(source for source in sources if source not in layered)

    scheduler = TaskScheduler()
    worker_count = scheduler.worker_count(len(pool_sources), requested_workers=workers)
    worker = DatasetAuditWorker(
        benchmark_enabled=benchmark,
        chunk_size=chunk_size,
        worker_count=worker_count,
    )
    result = ParallelBatchExecutor(scheduler).run(
        pool_sources,
        worker,
        requested_workers=workers,
        progress=ParallelConsoleProgress(),
    )
    quality_failed = False
    for item in result.items:
        if item.value is None:
            typer.echo(f"FAILED {item.source}: {item.error}")
            continue
        passed = _echo_audit_item(item.source, item.value.decision.engine, item.value.result)
        quality_failed = quality_failed or not passed
    layer_total = layer_failed = 0
    for source, layer_names in layered.items():
        for name in layer_names:
            layer_total += 1
            label = f"{source} layer={name}"
            try:
                layer_result = run_dataset_audit(source, layer=name)
            except (DataSourceError, OSError, TypeError, ValueError) as error:
                typer.echo(f"FAILED {label}: {type(error).__name__}: {error}")
                layer_failed += 1
                continue
            passed = _echo_audit_item(label, layer_result.metadata.engine, layer_result)
            quality_failed = quality_failed or not passed
    typer.echo(
        f"Audit complete: total={result.total + layer_total} "
        f"succeeded={result.succeeded + layer_total - layer_failed} "
        f"failed={result.failed + layer_failed}"
    )
    if benchmark:
        benchmark_report = BenchmarkReport(
            tuple(
                item.value.benchmark
                for item in result.items
                if item.value is not None and item.value.benchmark is not None
            )
        )
        try:
            write_benchmark_report(benchmark_report, benchmark_output, benchmark_format)
        except (OSError, ValueError) as error:
            typer.echo(f"Error writing benchmark report: {error}", err=True)
            raise typer.Exit(code=2) from error
        typer.echo(f"Benchmark report: {benchmark_output}")
    _echo_skipped(skipped)
    if not result.is_successful or layer_failed or quality_failed:
        raise typer.Exit(code=1)


@app.command("check")
def check_dataset(
    source: Annotated[Path, typer.Argument(help="Input vector dataset.")],
    profile_path: Annotated[
        Path | None,
        typer.Option("--profile", help="JSON or YAML quality profile."),
    ] = None,
    preset: Annotated[
        QualityPreset | None,
        typer.Option(help="Built-in preset when no profile is supplied."),
    ] = None,
    layer: Annotated[
        str | None,
        typer.Option(help="Layer name for a multi-layer GeoPackage."),
    ] = None,
    issues: Annotated[
        Path | None,
        typer.Option(help="Optional output GeoPackage containing issue layers."),
    ] = None,
    report: Annotated[
        Path | None,
        typer.Option(help="Optional .json or .html quality report."),
    ] = None,
    minimum_score: Annotated[
        float | None,
        typer.Option(min=0, max=100, help="Override the profile quality threshold."),
    ] = None,
    fail_on: Annotated[
        Severity | None,
        typer.Option(help="Override failure severity: info, warning, error, critical."),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Replace an existing issue GeoPackage."),
    ] = False,
) -> None:
    """Run the unified, profile-driven dataset quality workflow."""
    warnings.warn(
        "geoqc check is deprecated; use geoqc audit DATASET --profile PROFILE.",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        profile = (
            load_quality_profile(profile_path)
            if profile_path is not None
            else QualityProfile(
                name=f"{preset.value if preset else 'geometry'}-cli",
                preset=preset,
                require_crs=False,
            )
        )
        layers = _gpkg_layers(source) if layer is None else []
    except (DataSourceError, FileNotFoundError, OSError, TypeError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error

    policy = QualityGatePolicy(
        minimum_score=(minimum_score if minimum_score is not None else profile.gate.minimum_score),
        fail_on=fail_on or profile.gate.fail_on,
        allow_unknown_crs=profile.gate.allow_unknown_crs,
    )
    if len(layers) > 1:
        if issues is not None or report is not None:
            typer.echo(
                "Error: --issues and --report need --layer for a multi-layer GeoPackage.",
                err=True,
            )
            raise typer.Exit(code=2)
        worst = 0
        for name in layers:
            try:
                layer_result = run_dataset_audit(source, layer=name, profile=profile)
            except (DataSourceError, OSError, TypeError, ValueError) as error:
                typer.echo(f"QC error: dataset={source.name} layer={name} error={error}")
                worst = 2
                continue
            layer_passed = layer_result.passes(policy)
            typer.echo(
                f"QC complete: dataset={source.name} layer={name} "
                f"features={layer_result.feature_count} issues={len(layer_result.issues)} "
                f"score={layer_result.quality_score:.2f} "
                f"status={'PASS' if layer_passed else 'FAIL'}"
            )
            if not layer_passed:
                worst = max(worst, 1)
        if worst:
            raise typer.Exit(code=worst)
        return

    try:
        result = run_dataset_audit(source, layer=layer, profile=profile)
        if issues is not None:
            write_issue_layers(result, issues, overwrite=overwrite)
        if report is not None:
            write_audit_report(result, report)
    except (FileExistsError, FileNotFoundError, OSError, TypeError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error

    typer.echo(
        f"QC complete: dataset={result.dataset_name} features={result.feature_count} "
        f"issues={len(result.issues)} score={result.quality_score:.2f} "
        f"status={'PASS' if result.passes(policy) else 'FAIL'}"
    )
    if issues is not None:
        typer.echo(f"Issue layers: {issues.resolve()}")
    if report is not None:
        typer.echo(f"Report: {report.resolve()}")
    if not result.passes(policy):
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
