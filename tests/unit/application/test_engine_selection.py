"""Unit tests for deterministic engine selection policy."""

from geoqc.application.engine_selection import (
    GEOPANDAS_ENGINE,
    STREAMING_ENGINE,
    DatasetProfile,
    EngineDecisionService,
    GeometryComplexity,
)


def _profile(**changes: object) -> DatasetProfile:
    values: dict[str, object] = {
        "driver": "GPKG",
        "size_bytes": 1_000_000,
        "feature_count": 1_000,
        "estimated_memory_bytes": 10_000_000,
        "available_memory_bytes": 8_000_000_000,
        "geometry": GeometryComplexity(100, 5.0, 10),
    }
    values.update(changes)
    return DatasetProfile(**values)  # type: ignore[arg-type]


def test_small_dataset_uses_geopandas() -> None:
    decision = EngineDecisionService().select(_profile())
    assert decision.engine == GEOPANDAS_ENGINE


def test_large_feature_count_uses_streaming() -> None:
    decision = EngineDecisionService().select(_profile(feature_count=100_001))
    assert decision.engine == STREAMING_ENGINE
    assert "100,001 features" in " ".join(decision.reasons)


def test_low_available_memory_uses_streaming() -> None:
    decision = EngineDecisionService().select(
        _profile(estimated_memory_bytes=90_000_000, available_memory_bytes=100_000_000)
    )
    assert decision.engine == STREAMING_ENGINE
    assert "safe budget" in " ".join(decision.reasons)


def test_complex_projected_geometry_uses_streaming() -> None:
    decision = EngineDecisionService().select(
        _profile(
            feature_count=25_000,
            geometry=GeometryComplexity(100, 1_000.0, 2_000),
        )
    )
    assert decision.engine == STREAMING_ENGINE
    assert "projects to 25,000,000 vertices" in " ".join(decision.reasons)
