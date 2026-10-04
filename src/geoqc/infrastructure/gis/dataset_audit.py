"""Dataset audit for the canonical dataset workflow."""

import warnings
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import pyogrio  # type: ignore[import-untyped]

from geoqc.domain.models import (
    AuditDatasetMetadata,
    DatasetAuditResult,
    DatasetLayer,
    QualityPreset,
    QualityProfile,
)
from geoqc.infrastructure.gis.dataset_checks import (
    _attach_feature_ids,
    _attribute_issues,
    _check_name,
    _checks_for_result,
    _crs_issues,
    _geometry_type_issues,
    _metric_skip_reason,
)
from geoqc.infrastructure.gis.dataset_export import _ResultExporter
from geoqc.infrastructure.gis.dataset_scoring import _rebuild_result
from geoqc.infrastructure.gis.dataset_values import _feature_attributes, _wkt
from geoqc.infrastructure.gis.legacy import profile_from_legacy_arguments
from geoqc.infrastructure.gis.profile_loading import _DEFAULT_PROFILE, _resolve_profile
from geoqc.infrastructure.gis.quality_workflow import (
    audit_geometries,
    evaluate_topology_rules,
)

_SUPPORTED_SUFFIXES = frozenset({".fgb", ".geojson", ".gpkg", ".json", ".parquet", ".shp"})


def audit_geodataframe(
    frame: gpd.GeoDataFrame,
    *,
    dataset_name: str = "dataset",
    profile: QualityProfile | None = None,
    preset: QualityPreset | str | None = None,
) -> DatasetAuditResult:
    """Run geometry, topology, CRS, and attribute checks in one workflow."""
    if not isinstance(frame, gpd.GeoDataFrame):
        raise TypeError("frame must be a GeoDataFrame")
    if frame.geometry.name not in frame.columns:
        raise ValueError("frame must have an active geometry column")
    selected_preset = profile.preset if profile is not None else preset
    if profile is not None and profile.expected_geometry_types:
        allowed_types = {item.casefold() for item in profile.expected_geometry_types}
        if any(geometry.geom_type.casefold() not in allowed_types for geometry in frame.geometry):
            selected_preset = None
    crs = frame.crs.to_string() if frame.crs is not None else None
    metric_safe = profile is None or _metric_skip_reason(frame, profile) is None
    base = audit_geometries(
        tuple(frame.geometry),
        dataset_name=dataset_name,
        preset=selected_preset,
        crs=crs,
        tolerance=profile.tolerance if profile and metric_safe else 0.0,
        minimum_area=profile.minimum_area if profile and metric_safe else 0.0,
        scoring=profile.scoring if profile else None,
        profile_name=profile.name if profile else None,
    )
    issues = list(base.issues)
    if profile is not None:
        issues.extend(_geometry_type_issues(frame, dataset_name, profile))
        issues.extend(_attribute_issues(frame, dataset_name, profile.attribute_rules))
        issues.extend(_crs_issues(frame, dataset_name, profile))
        local_rules = tuple(
            rule
            for rule in profile.topology_rules
            if rule.layer == dataset_name and rule.reference_layer is None
        )
        if local_rules and _metric_skip_reason(frame, profile) is None:
            layer = DatasetLayer(
                dataset_name,
                tuple(_wkt(item) for item in frame.geometry),
                crs,
                _feature_attributes(frame),
            )
            issues.extend(evaluate_topology_rules((layer,), local_rules))
        issues = _attach_feature_ids(issues, frame, profile.id_column)
        issues = [
            replace(
                issue,
                severity=profile.severity_overrides.get(
                    issue.code,
                    profile.severity_overrides.get(issue.category, issue.severity),
                ),
            )
            for issue in issues
            if _check_name(issue.category) in profile.enabled_checks
        ]
    return _rebuild_result(base, issues, profile.scoring if profile else None)


def audit_dataset(
    source: str | Path,
    *,
    layer: str | None = None,
    profile: QualityProfile | str | Path | None = None,
    preset: QualityPreset | str | None = None,
    schema: object | None = None,
    checks: str | Sequence[str] = "all",
    chunk_size: int = 16_384,
) -> DatasetAuditResult:
    """Canonical file-based dataset QC entry point used by Python and CLI."""
    selected_profile = _resolve_profile(profile)
    if schema is not None or checks != "all" or chunk_size != 16_384:
        warnings.warn(
            "schema/checks/chunk_size are deprecated audit_dataset arguments; migrate "
            "them to a QualityProfile.",
            DeprecationWarning,
            stacklevel=2,
        )
        from geoqc.domain.models import AttributeSchema

        if schema is not None and not isinstance(schema, AttributeSchema):
            raise TypeError("schema must be an AttributeSchema")
        selected_profile = profile_from_legacy_arguments(
            selected_profile or _DEFAULT_PROFILE,
            schema=schema,
            checks=checks,
        )
    return _audit_file_impl(source, layer=layer, profile=selected_profile, preset=preset)


def _audit_file_impl(
    source: str | Path,
    *,
    layer: str | None,
    profile: QualityProfile | None,
    preset: QualityPreset | str | None,
) -> DatasetAuditResult:
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.casefold() not in _SUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported dataset format: {path.suffix}")
    selected_layer = layer
    if path.suffix.casefold() == ".gpkg":
        layers = [str(item[0]) for item in pyogrio.list_layers(path)]
        if selected_layer is None and len(layers) > 1:
            raise ValueError("GeoPackage contains multiple layers; specify layer")
        if selected_layer is not None and selected_layer not in layers:
            raise ValueError(f"unknown layer {selected_layer!r}; available layers: {layers}")
        selected_layer = selected_layer or layers[0]
    if path.suffix.casefold() == ".parquet":
        frame = gpd.read_parquet(path)
    else:
        frame = gpd.read_file(path, layer=selected_layer)
    result = audit_geodataframe(
        frame,
        dataset_name=selected_layer or path.stem,
        profile=profile,
        preset=preset,
    )
    metadata = AuditDatasetMetadata(
        path=str(path.resolve()),
        layer=selected_layer,
        driver=path.suffix.lstrip(".").upper(),
        crs=frame.crs.to_string() if frame.crs is not None else None,
        feature_count=len(frame),
        geometry_column=frame.geometry.name,
        size_bytes=path.stat().st_size,
        engine="geopandas",
    )
    return replace(
        result,
        metadata=metadata,
        checks=_checks_for_result(result, profile),
        _exporter=_ResultExporter(),
    )


def audit_layers(
    frames: Mapping[str, gpd.GeoDataFrame], *, profile: QualityProfile
) -> DatasetAuditResult:
    """Audit multiple named layers and include configured cross-layer rules."""
    if not frames:
        raise ValueError("at least one layer is required")
    results = [
        audit_geodataframe(frame, dataset_name=name, profile=profile)
        for name, frame in frames.items()
    ]
    layers = tuple(
        DatasetLayer(
            name,
            tuple(_wkt(item) for item in frame.geometry),
            frame.crs.to_string() if frame.crs is not None else None,
            _feature_attributes(frame),
        )
        for name, frame in frames.items()
    )
    cross_rules = tuple(rule for rule in profile.topology_rules if rule.reference_layer is not None)
    issues = [issue for result in results for issue in result.issues]
    issues.extend(evaluate_topology_rules(layers, cross_rules))
    first = results[0]
    combined = DatasetAuditResult(
        dataset_name=profile.name,
        preset=profile.preset,
        feature_count=sum(result.feature_count for result in results),
        issues=(),
        crs_guard=first.crs_guard,
        category_scores=(),
        quality_score=100.0,
        profile_name=profile.name,
    )
    return _rebuild_result(combined, issues, profile.scoring)
