"""Profile loading for the canonical dataset workflow."""

import json
from collections.abc import Mapping
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from geoqc.domain.models import (
    QualityGatePolicy,
    QualityPreset,
    QualityProfile,
    ScoringPolicy,
)
from geoqc.domain.rules import Severity
from geoqc.infrastructure.gis.dataset_export import _atomic_text
from geoqc.infrastructure.gis.profile_schema import (
    _attribute_rule,
    _boolean,
    _integer,
    _mapping,
    _number,
    _profile_dict,
    _reject_unknown,
    _sequence,
    _topology_rule,
)

_BUILTIN_PROFILES = {
    "parcel": QualityProfile(
        name="parcel",
        preset=QualityPreset.PARCEL,
        expected_geometry_types=("Polygon", "MultiPolygon"),
        require_crs=True,
        require_projected_crs=True,
    ),
    "road-network": QualityProfile(
        name="road-network",
        preset=QualityPreset.ROAD,
        expected_geometry_types=("LineString", "MultiLineString"),
        require_crs=True,
        require_projected_crs=True,
    ),
    "administrative-boundary": QualityProfile(
        name="administrative-boundary",
        preset=QualityPreset.ADMIN_BOUNDARY,
        expected_geometry_types=("Polygon", "MultiPolygon"),
        require_crs=True,
        require_projected_crs=True,
    ),
}


_DEFAULT_PROFILE = QualityProfile(name="default", require_crs=True)


def load_quality_profile(source: str | Path) -> QualityProfile:
    """Load and validate a versioned JSON or YAML quality profile."""
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.casefold() == ".json":
        raw = json.loads(text)
    elif path.suffix.casefold() in {".yaml", ".yml"}:
        raw = yaml.safe_load(text)
    else:
        raise ValueError("quality profile must use .json, .yaml, or .yml")
    if not isinstance(raw, dict):
        raise ValueError("quality profile root must be an object")
    return quality_profile_from_dict(raw)


def quality_profile_from_dict(raw: Mapping[str, object]) -> QualityProfile:
    """Validate a mapping and build an immutable quality profile."""
    allowed = {
        "name",
        "id_column",
        "version",
        "preset",
        "tolerance",
        "minimum_area",
        "enabled_checks",
        "expected_geometry_types",
        "crs",
        "topology_rules",
        "attribute_rules",
        "attribute_schema",
        "severity_overrides",
        "scoring",
        "quality_gate",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"unknown quality profile fields: {unknown}")
    crs = _mapping(raw.get("crs", {}), "crs")
    scoring_raw = _mapping(raw.get("scoring", {}), "scoring")
    gate_raw = _mapping(raw.get("quality_gate", {}), "quality_gate")
    _reject_unknown(crs, {"required", "require_projected", "allowed"}, "crs")
    _reject_unknown(
        scoring_raw,
        {"category_weights", "severity_penalties", "category_caps", "repeated_feature_cap"},
        "scoring",
    )
    _reject_unknown(
        gate_raw,
        {"minimum_score", "fail_on", "allow_unknown_crs"},
        "quality_gate",
    )
    weights = scoring_raw.get("category_weights")
    penalties = scoring_raw.get("severity_penalties")
    scoring = ScoringPolicy(
        category_weights=(
            {
                str(key): _number(value, f"category weight {key}")
                for key, value in _mapping(weights, "category_weights").items()
            }
            if weights is not None
            else ScoringPolicy().category_weights
        ),
        severity_penalties=(
            {
                Severity(str(key)): _number(value, f"severity penalty {key}")
                for key, value in _mapping(penalties, "severity_penalties").items()
            }
            if penalties is not None
            else ScoringPolicy().severity_penalties
        ),
        category_caps=(
            {
                str(key): _number(value, f"category cap {key}")
                for key, value in _mapping(scoring_raw["category_caps"], "category_caps").items()
            }
            if "category_caps" in scoring_raw
            else {}
        ),
        repeated_feature_cap=_number(
            scoring_raw.get("repeated_feature_cap", 30.0), "scoring.repeated_feature_cap"
        ),
    )
    attribute_raw = raw.get("attribute_schema", raw.get("attribute_rules", ()))
    if "attribute_schema" in raw and "attribute_rules" in raw:
        raise ValueError("use attribute_schema; do not also provide attribute_rules")
    return QualityProfile(
        name=str(raw.get("name", "")).strip(),
        version=_integer(raw.get("version", 1), "version"),
        preset=QualityPreset(str(raw["preset"])) if raw.get("preset") is not None else None,
        tolerance=_number(raw.get("tolerance", 0.0), "tolerance"),
        minimum_area=_number(raw.get("minimum_area", 0.0), "minimum_area"),
        require_crs=_boolean(crs.get("required", True), "crs.required"),
        require_projected_crs=_boolean(
            crs.get("require_projected", False), "crs.require_projected"
        ),
        allowed_crs=tuple(str(item) for item in _sequence(crs.get("allowed", ()), "crs.allowed")),
        id_column=str(raw["id_column"]) if raw.get("id_column") is not None else None,
        enabled_checks=tuple(
            str(item)
            for item in _sequence(
                raw.get(
                    "enabled_checks",
                    ("geometry", "crs", "attributes", "topology", "spatial"),
                ),
                "enabled_checks",
            )
        ),
        expected_geometry_types=tuple(
            str(item)
            for item in _sequence(raw.get("expected_geometry_types", ()), "expected_geometry_types")
        ),
        topology_rules=tuple(
            _topology_rule(_mapping(item, "topology rule"))
            for item in _sequence(raw.get("topology_rules", ()), "topology_rules")
        ),
        attribute_rules=tuple(
            _attribute_rule(_mapping(item, "attribute rule"))
            for item in _sequence(attribute_raw, "attribute_schema")
        ),
        severity_overrides={
            str(key): Severity(str(value))
            for key, value in _mapping(
                raw.get("severity_overrides", {}), "severity_overrides"
            ).items()
        },
        scoring=scoring,
        gate=QualityGatePolicy(
            minimum_score=_number(gate_raw.get("minimum_score", 75.0), "minimum_score"),
            fail_on=Severity(str(gate_raw.get("fail_on", "error"))),
            allow_unknown_crs=_boolean(
                gate_raw.get("allow_unknown_crs", False), "quality_gate.allow_unknown_crs"
            ),
        ),
    )


def dump_quality_profile(profile: QualityProfile, destination: str | Path) -> Path:
    """Write a profile as deterministic JSON or YAML."""
    path = Path(destination)
    payload = _profile_dict(profile)
    if path.suffix.casefold() == ".json":
        text = json.dumps(payload, indent=2, sort_keys=True)
    elif path.suffix.casefold() in {".yaml", ".yml"}:
        text = yaml.safe_dump(payload, sort_keys=False)
    else:
        raise ValueError("quality profile must use .json, .yaml, or .yml")
    _atomic_text(path, text)
    return path


def _resolve_profile(profile: QualityProfile | str | Path | None) -> QualityProfile | None:
    if profile is None:
        return _DEFAULT_PROFILE
    if isinstance(profile, QualityProfile):
        return profile
    key = str(profile).casefold()
    if key in _BUILTIN_PROFILES:
        return _BUILTIN_PROFILES[key]
    return load_quality_profile(profile)
