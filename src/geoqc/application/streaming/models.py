"""Framework-independent value objects used by the streaming pipeline."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

PredicateOperator = Literal[
    "==", "!=", "<", "<=", ">", ">=", "in", "not in", "is null", "is not null"
]


@dataclass(frozen=True, slots=True)
class ScanPredicate:
    """One backend-neutral predicate eligible for storage-level pushdown."""

    column: str
    operator: PredicateOperator
    value: Any = None

    def __post_init__(self) -> None:
        if not self.column:
            raise ValueError("predicate column cannot be empty")
        if self.operator in {"in", "not in"} and not isinstance(
            self.value, (tuple, list, set, frozenset)
        ):
            raise ValueError(f"{self.operator!r} predicate requires a collection value")


@dataclass(frozen=True, slots=True)
class ScanOptions:
    """Optional projection and filtering hints for lazy dataset readers."""

    columns: tuple[str, ...] | None = None
    predicates: tuple[ScanPredicate, ...] = ()
    include_geometry: bool = True
    use_threads: bool = True
    batch_readahead: int = 4
    fragment_readahead: int = 1

    def __post_init__(self) -> None:
        if self.columns is not None:
            if not self.columns or any(not column for column in self.columns):
                raise ValueError("columns must contain at least one non-empty name")
            if len(set(self.columns)) != len(self.columns):
                raise ValueError("columns cannot contain duplicates")
        if self.batch_readahead < 0 or self.fragment_readahead < 0:
            raise ValueError("readahead values cannot be negative")


@dataclass(frozen=True, slots=True)
class DatasetSource:
    """A local dataset and an optional named layer."""

    path: Path
    layer: str | None = None
    encoding: str | None = None
    scan: ScanOptions | None = None


@dataclass(frozen=True, slots=True)
class DatasetMetadata:
    """Metadata required to plan a bounded streaming read."""

    driver: str
    layer: str | None
    crs: str | None
    feature_count: int | None
    geometry_column: str
    encoding: str | None = None


@dataclass(frozen=True, slots=True)
class FeatureChunk:
    """One bounded batch with a stable dataset-wide offset."""

    offset: int
    features: Any
    size: int

    def __post_init__(self) -> None:
        if self.offset < 0:
            raise ValueError("Chunk offset cannot be negative")
        if self.size < 0:
            raise ValueError("Chunk size cannot be negative")


@dataclass(frozen=True, slots=True)
class StreamingConfig:
    """Resource bounds for one streaming execution."""

    chunk_size: int = 65_536
    minimum_chunk_size: int = 256

    def __post_init__(self) -> None:
        if self.chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        if self.minimum_chunk_size < 1:
            raise ValueError("minimum_chunk_size must be positive")
        if self.minimum_chunk_size > self.chunk_size:
            raise ValueError("minimum_chunk_size cannot exceed chunk_size")


@dataclass(frozen=True, slots=True)
class StreamingResult:
    """Final output and execution statistics returned by the orchestrator."""

    result: Any
    metadata: DatasetMetadata
    feature_count: int
    chunk_count: int
