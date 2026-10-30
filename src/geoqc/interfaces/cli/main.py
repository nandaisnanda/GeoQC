"""Typer composition root for the GeoQC command-line interface."""

import json
import warnings
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import click
import geopandas as gpd  # type: ignore[import-untyped]
import shapely
import typer
from pyogrio import list_layers, read_info  # type: ignore[import-untyped]
from pyogrio.errors import DataSourceError  # type: ignore[import-untyped]
from typer.core import TyperGroup

from geoqc import (
    CheckStatus,
    QualityGatePolicy,
    QualityPreset,
    QualityProfile,
    RepairConfig,
    RepairIssueType,
    __version__,
    load_quality_profile,
    repair_geometries,
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
from geoqc.domain.models import DatasetAuditResult, RepairStatus
from geoqc.domain.models.spatial_intelligence import RoadNetworkRepairConfig
from geoqc.domain.rules import Severity
from geoqc.infrastructure.gis.dataset_checks import MISSING_CRS_MESSAGE
from geoqc.infrastructure.gis.parallel_audit import (
    DatasetAudit,
    DatasetAuditWorker,
    audit_dataset_worker,
)
from geoqc.infrastructure.gis.profile_loading import (
    _generic_profile,
    list_builtin_presets,
    load_builtin_preset,
)
from geoqc.infrastructure.gis.road_dataset_repair import RoadDatasetRepairer
from geoqc.infrastructure.reporting import BenchmarkFormat, write_benchmark_report
from geoqc.interfaces.cli.delivery import app as delivery_app
from geoqc.interfaces.cli.progress import ParallelConsoleProgress

_COMMAND_ORDER = ("check", "fix", "audit", "repair-roads", "presets")
_ADVANCED_COMMANDS = frozenset({"batch", "html-report", "crs-scan", "axis-order", "datum-shift"})


class _OrderedGroup(TyperGroup):
    """List the everyday commands first, in a fixed order."""

    def list_commands(self, ctx: click.Context) -> list[str]:
        names = super().list_commands(ctx)
        first = [name for name in _COMMAND_ORDER if name in names]
        return first + [name for name in names if name not in first]


app: typer.Typer = typer.Typer(
    cls=_OrderedGroup,
    name="geoqc",
    help="GeoQC GIS quality-control toolkit.",
    invoke_without_command=True,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


app.add_typer(delivery_app)
# Advanced commands keep working but stay out of `geoqc --help`.
for _command in delivery_app.registered_commands:
    _name = _command.name or (
        _command.callback.__name__.replace("_", "-") if _command.callback else ""
    )
    if _name in _ADVANCED_COMMANDS:
        _command.hidden = True

AUDIT_SUFFIXES = (".fgb", ".geojson", ".gpkg", ".parquet", ".shp")
_SHAPEFILE_SIDECARS = frozenset(
    {".cpg", ".dbf", ".prj", ".qix", ".qmd", ".sbn", ".sbx", ".shx", ".xml"}
)


OUTPUT_DIR_NAME = "geoqc_output"


def _is_check_output(path: Path, folder: Path) -> bool:
    """Whether a file found under a folder input is a `check` output, not data."""
    if path.name.casefold().endswith("_issues.gpkg"):
        return True
    return OUTPUT_DIR_NAME in path.relative_to(folder).parts[:-1]


def _drop_check_outputs(inputs: list[Path], sources: tuple[Path, ...]) -> tuple[Path, ...]:
    """Remove `check` outputs found via folder inputs; files named directly stay."""
    explicit = {item.resolve() for item in inputs if item.is_file()}
    folders = [item.resolve() for item in inputs if item.is_dir()]
    return tuple(
        source
        for source in sources
        if source in explicit
        or not any(
            source.is_relative_to(folder) and _is_check_output(source, folder) for folder in folders
        )
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
            if resolved.is_relative_to(folder.resolve()) and _is_check_output(
                resolved, folder.resolve()
            ):
                continue
            if (
                candidate.suffix.casefold() in _SHAPEFILE_SIDECARS
                and (resolved.parent, resolved.stem.casefold()) in shapefiles
            ):
                continue
            skipped.append(candidate.relative_to(folder).as_posix())
    return sorted(skipped, key=str.casefold)


def _echo_missing_crs(result: DatasetAuditResult) -> None:
    for issue in result.issues:
        if issue.code == "META-MISSING_CRS":
            typer.echo(f"CRS: missing. {issue.message.removeprefix(MISSING_CRS_MESSAGE)}".strip())
            return


def _echo_unmatched_rules(profile: QualityProfile | None, dataset_name: str) -> None:
    """Warn when a profile's topology rules name layers other than this dataset."""
    layers = sorted({rule.layer for rule in profile.topology_rules}) if profile else []
    if layers and dataset_name not in layers:
        typer.echo(
            f"Warning: no topology rule applies to '{dataset_name}'; the profile targets "
            f"layer(s) {', '.join(layers)}. Use --layer or rename the layer to match."
        )


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


def _echo_verdict(result: DatasetAuditResult, passed: bool) -> None:
    """Print why the check passed or failed, then the most frequent issue codes."""
    counts = Counter(issue.severity for issue in result.issues)
    parts = [
        f"{counts[level]} {level.value}{'s' if counts[level] > 1 else ''}"
        for level in (Severity.CRITICAL, Severity.ERROR, Severity.WARNING, Severity.INFO)
        if counts[level]
    ]
    score = f"score {result.quality_score:.0f}/100"
    if passed:
        typer.echo(f"PASS ({score})")
    else:
        typer.echo(f"FAIL: {', '.join(parts) or 'quality gate not met'} ({score})")
    for code, count in Counter(issue.code for issue in result.issues).most_common(3):
        typer.echo(f"  {code} x{count}")


def _gpkg_layers(source: Path) -> list[str]:
    """Return GeoPackage layer names, or an empty list for other inputs."""
    if source.suffix.casefold() != ".gpkg" or not source.is_file():
        return []
    return [str(item[0]) for item in list_layers(source)]


def _auto_profile(source: Path, layer: str | None) -> QualityProfile:
    """Pick a generic profile from the layer geometry type and say which one."""
    geometry_type = read_info(source, layer=layer).get("geometry_type")
    profile = _generic_profile(geometry_type) or QualityProfile(
        name="geometry-cli", require_crs=False
    )
    target = source.name if layer is None else f"{source.name}:{layer}"
    typer.echo(f"Preset: {profile.name} (geometry type {geometry_type or 'unknown'} in {target})")
    if profile.name == "generic-line":
        # Unknown lines may be rivers or contours: run geometry checks only.
        typer.echo("Road network checks off; use --preset jalan for roads.")
        profile = replace(profile, preset=None)
    return profile


def _preset_profile(name: str) -> QualityProfile:
    """Resolve a packaged Indonesian preset or a generic preset by name."""
    if name in list_builtin_presets():
        return load_builtin_preset(name)
    try:
        generic = QualityPreset(name)
    except ValueError:
        valid = ", ".join([*list_builtin_presets(), *(item.value for item in QualityPreset)])
        raise ValueError(f"unknown preset '{name}'. Valid presets: {valid}") from None
    return QualityProfile(name=f"{generic.value}-cli", preset=generic, require_crs=False)


_REPORT_HINT = 'HTML report skipped: install the report extra with pip install "geoqc[report]".'


def _default_output(source: Path, layer: str | None, suffix: str) -> Path:
    stem = source.stem if layer is None else f"{source.stem}_{layer}"
    return source.parent / OUTPUT_DIR_NAME / f"{stem}_{suffix}"


def _write_check_outputs(
    result: DatasetAuditResult,
    issues: Path | None,
    report: Path | None,
    *,
    overwrite_issues: bool,
    overwrite_report: bool,
) -> list[str]:
    """Write the issue GeoPackage and report, returning the lines to print."""
    lines = []
    for target in (issues, report):
        if target is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
    if issues is not None:
        write_issue_layers(result, issues, overwrite=overwrite_issues)
        lines.append(f"Issue layers: {issues.resolve()}")
    if report is not None:
        try:
            write_audit_report(result, report, overwrite=overwrite_report)
        except ImportError:
            lines.append(_REPORT_HINT)
        else:
            lines.append(f"Report: {report.resolve()}")
    return lines


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


@app.command(short_help="Check many files or folders for geometry, CRS and duplicate problems.")
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
        sources = _drop_check_outputs(inputs, discovery.discover(inputs, recursive=recursive))
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


@app.command("presets", short_help="List the built-in presets for check --preset.")
def list_presets() -> None:
    """List the built-in presets for `geoqc check --preset`."""
    descriptions = {
        **list_builtin_presets(),
        **{item.value: "Generic preset by geometry type." for item in QualityPreset},
    }
    width = max(len(name) for name in descriptions)
    for name, description in descriptions.items():
        typer.echo(f"{name.ljust(width)}  {description}")


@app.command(
    "check",
    short_help="Check one dataset for errors and write an issue layer you can open in QGIS.",
)
def check_dataset(
    source: Annotated[Path, typer.Argument(help="Input vector dataset.")],
    profile_path: Annotated[
        Path | None,
        typer.Option("--profile", help="JSON or YAML quality profile."),
    ] = None,
    preset: Annotated[
        str | None,
        typer.Option(help="Built-in preset when no profile is supplied. See `geoqc presets`."),
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
    no_output: Annotated[
        bool,
        typer.Option(
            "--no-output",
            help="Skip the default report and issue GeoPackage written next to the input.",
        ),
    ] = False,
) -> None:
    """Run the unified, profile-driven dataset quality workflow."""
    warnings.warn(
        "geoqc check is deprecated; use geoqc audit DATASET --profile PROFILE.",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        profile: QualityProfile | None = None
        if profile_path is not None:
            profile = load_quality_profile(profile_path)
        elif preset is not None:
            profile = _preset_profile(preset)
        layers = _gpkg_layers(source) if layer is None else []
        if profile is None and len(layers) <= 1:
            profile = _auto_profile(source, layer)
    except (DataSourceError, FileNotFoundError, OSError, TypeError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error

    # Generic profiles use the default gate, so a per-layer pick does not change it.
    gate = profile.gate if profile is not None else QualityGatePolicy()
    policy = QualityGatePolicy(
        minimum_score=(minimum_score if minimum_score is not None else gate.minimum_score),
        fail_on=fail_on or gate.fail_on,
        allow_unknown_crs=gate.allow_unknown_crs,
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
                layer_profile = profile or _auto_profile(source, name)
                layer_result = run_dataset_audit(source, layer=name, profile=layer_profile)
                written = (
                    []
                    if no_output
                    else _write_check_outputs(
                        layer_result,
                        _default_output(source, name, "issues.gpkg"),
                        _default_output(source, name, "report.html"),
                        overwrite_issues=True,
                        overwrite_report=True,
                    )
                )
            except (DataSourceError, OSError, TypeError, ValueError) as error:
                typer.echo(f"QC error: dataset={source.name} layer={name} error={error}")
                worst = 2
                continue
            layer_passed = layer_result.passes(policy)
            _echo_unmatched_rules(layer_profile, name)
            typer.echo(
                f"QC complete: dataset={source.name} layer={name} "
                f"features={layer_result.feature_count} issues={len(layer_result.issues)} "
                f"score={layer_result.quality_score:.2f} "
                f"status={'PASS' if layer_passed else 'FAIL'}"
            )
            _echo_verdict(layer_result, layer_passed)
            for line in written:
                typer.echo(line)
            if not layer_passed:
                worst = max(worst, 1)
        if worst:
            raise typer.Exit(code=worst)
        return

    # Default outputs are regenerated on every run; explicit paths keep --overwrite rules.
    issues_path = issues or (None if no_output else _default_output(source, layer, "issues.gpkg"))
    report_path = report or (None if no_output else _default_output(source, layer, "report.html"))
    try:
        result = run_dataset_audit(source, layer=layer, profile=profile)
        written = _write_check_outputs(
            result,
            issues_path,
            report_path,
            overwrite_issues=overwrite or issues is None,
            overwrite_report=report is None,
        )
    except (FileExistsError, FileNotFoundError, OSError, TypeError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from error

    typer.echo(
        f"QC complete: dataset={result.dataset_name} features={result.feature_count} "
        f"issues={len(result.issues)} score={result.quality_score:.2f} "
        f"status={'PASS' if result.passes(policy) else 'FAIL'}"
    )
    _echo_verdict(result, result.passes(policy))
    _echo_missing_crs(result)
    _echo_unmatched_rules(profile, result.dataset_name)
    for line in written:
        typer.echo(line)
    if not result.passes(policy):
        raise typer.Exit(code=1)


@app.command(
    "repair-roads",
    short_help="Close small gaps and node intersections in a road layer, saved as a new file.",
)
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


# Shape-preserving fixes only; overlaps and gaps change shared boundaries.
_SAFE_FIX_CONFIG = RepairConfig(resolve_overlaps=False, fill_gaps=False)
# Preview-only pass: detects every overlap and enclosed gap without applying it.
_REVIEW_CONFIG = RepairConfig(gap_area_threshold=float("inf"))
_REVIEW_ISSUES = (RepairIssueType.OVERLAP, RepairIssueType.GAP)


@app.command(
    "fix",
    short_help="Repair safe geometry errors into a new file; overlaps and gaps are only flagged.",
)
def fix(
    source: Annotated[Path, typer.Argument(help="Input vector dataset; never modified.")],
    output: Annotated[Path, typer.Argument(help="New output GeoPackage path.")],
    layer: Annotated[
        str | None,
        typer.Option(help="Input layer name; required for multi-layer datasets."),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Replace an existing output GeoPackage."),
    ] = False,
) -> None:
    """Apply safe geometry fixes and flag overlaps and gaps for review."""
    try:
        if output.suffix.lower() != ".gpkg":
            raise ValueError("Output must be a .gpkg file.")
        if output.resolve() == source.resolve():
            raise ValueError("Output path must differ from the input path.")
        if output.exists() and not overwrite:
            raise FileExistsError(f"Output exists: {output}. Pass --overwrite to replace it.")
        if not source.exists():
            raise FileNotFoundError(f"Input not found: {source}")
        if layer is None:
            layers = list_layers(source)
            if len(layers) > 1:
                names = ", ".join(str(row[0]) for row in layers)
                raise ValueError(f"Input has multiple layers ({names}); pass --layer.")
        frame = gpd.read_file(source, layer=layer)
        positions = [
            index
            for index, geometry in enumerate(frame.geometry)
            if geometry is not None and not geometry.is_empty
        ]
        geometries = [frame.geometry.iloc[index] for index in positions]
        safe = repair_geometries(geometries, _SAFE_FIX_CONFIG)
        safe_geometries = [shapely.from_wkt(wkt) for wkt in safe.after_wkt]
        preview = repair_geometries(safe_geometries, _REVIEW_CONFIG)

        reasons: list[set[str]] = [set() for _ in geometries]
        for item in safe.report.results:
            if item.result.status is RepairStatus.FAILED:
                reasons[item.feature_index].add("repair_failed")
        for item in preview.report.results:
            for action in item.result.actions:
                if action.issue_type in _REVIEW_ISSUES:
                    reasons[item.feature_index].add(str(action.issue_type.value))

        output_geometries = list(frame.geometry)
        review_column: list[str | None] = [None] * len(frame)
        for offset, index in enumerate(positions):
            output_geometries[index] = safe_geometries[offset]
            if reasons[offset]:
                review_column[index] = ",".join(sorted(reasons[offset]))
        fixed = frame.set_geometry(
            gpd.GeoSeries(output_geometries, index=frame.index, crs=frame.crs)
        )
        fixed["geoqc_review"] = review_column

        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.stem}.{uuid4().hex}.gpkg")
        try:
            fixed.to_file(temporary, layer=layer or source.stem, driver="GPKG")
            temporary.replace(output)
        finally:
            if temporary.exists():
                temporary.unlink()
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

    needs_review = sum(1 for item in reasons if item)
    typer.echo(f"Fixed {safe.report.repaired_count}, needs review {needs_review}")
    typer.echo(f"Output: {output.resolve()} layer={layer or source.stem}")


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
