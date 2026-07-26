"""Extensible policy service for automatic engine selection."""

from collections.abc import Sequence
from typing import Protocol

from geoqc.application.engine_selection.models import (
    GEOPANDAS_ENGINE,
    STREAMING_ENGINE,
    DatasetProfile,
    EngineDecision,
    EngineSelectionConfig,
)


class SelectionRule(Protocol):
    """One independently testable reason to require streaming."""

    def evaluate(self, profile: DatasetProfile, config: EngineSelectionConfig) -> str | None: ...


class _MemoryRule:
    def evaluate(self, profile: DatasetProfile, config: EngineSelectionConfig) -> str | None:
        limit = config.maximum_memory_bytes
        if profile.available_memory_bytes is not None:
            limit = min(
                limit, int(profile.available_memory_bytes * config.available_memory_fraction)
            )
        if profile.estimated_memory_bytes > limit:
            return (
                f"estimated in-memory footprint is {_human_bytes(profile.estimated_memory_bytes)}, "
                f"above the safe budget of {_human_bytes(limit)}"
            )
        return None


class _FeatureCountRule:
    def evaluate(self, profile: DatasetProfile, config: EngineSelectionConfig) -> str | None:
        if profile.feature_count is not None and profile.feature_count > config.maximum_features:
            return f"dataset contains approximately {profile.feature_count:,} features"
        return None


class _FileSizeRule:
    def evaluate(self, profile: DatasetProfile, config: EngineSelectionConfig) -> str | None:
        if profile.size_bytes > config.maximum_file_bytes:
            return f"dataset size is {_human_bytes(profile.size_bytes)}"
        return None


class _GeometryComplexityRule:
    def evaluate(self, profile: DatasetProfile, config: EngineSelectionConfig) -> str | None:
        geometry = profile.geometry
        projected = int(geometry.average_vertices * (profile.feature_count or 0))
        if (
            geometry.average_vertices >= config.complex_average_vertices
            and projected >= config.complex_projected_vertices
        ):
            return (
                f"geometry sample averages {geometry.average_vertices:,.0f} vertices and projects "
                f"to {projected:,} vertices"
            )
        return None


class EngineDecisionService:
    """Choose an engine without importing either engine or the Rule Engine."""

    def __init__(
        self,
        config: EngineSelectionConfig | None = None,
        rules: Sequence[SelectionRule] | None = None,
    ) -> None:
        self._config = config or EngineSelectionConfig()
        self._rules = tuple(
            rules
            or (_MemoryRule(), _FeatureCountRule(), _FileSizeRule(), _GeometryComplexityRule())
        )

    def select(self, profile: DatasetProfile) -> EngineDecision:
        reasons = tuple(
            reason
            for rule in self._rules
            if (reason := rule.evaluate(profile, self._config)) is not None
        )
        if reasons:
            return EngineDecision(STREAMING_ENGINE, reasons, profile)
        return EngineDecision(
            GEOPANDAS_ENGINE,
            ("dataset is within configured in-memory safety limits",),
            profile,
        )


def _human_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024.0 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024.0
    raise AssertionError("unreachable")
