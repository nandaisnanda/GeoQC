"""Pure value objects used to select an audit execution engine."""

from dataclasses import dataclass

GEOPANDAS_ENGINE = "geopandas"
STREAMING_ENGINE = "streaming"


@dataclass(frozen=True, slots=True)
class GeometryComplexity:
    """Bounded geometry sample statistics."""

    sampled_features: int = 0
    average_vertices: float = 0.0
    maximum_vertices: int = 0


@dataclass(frozen=True, slots=True)
class DatasetProfile:
    """Cheap dataset characteristics; no full dataset content is retained."""

    driver: str
    size_bytes: int
    feature_count: int | None
    estimated_memory_bytes: int
    available_memory_bytes: int | None
    geometry: GeometryComplexity = GeometryComplexity()


@dataclass(frozen=True, slots=True)
class EngineSelectionConfig:
    """Conservative defaults for safe in-memory execution."""

    maximum_file_bytes: int = 64 * 1024 * 1024
    maximum_features: int = 100_000
    maximum_memory_bytes: int = 512 * 1024 * 1024
    available_memory_fraction: float = 0.35
    complex_average_vertices: float = 1_000.0
    complex_projected_vertices: int = 20_000_000


@dataclass(frozen=True, slots=True)
class EngineDecision:
    """Selected engine and stable, human-readable reasons."""

    engine: str
    reasons: tuple[str, ...]
    profile: DatasetProfile
