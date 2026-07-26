"""Domain value objects for CRS consistency audits."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class DatasetSource:
    """A GIS dataset and optional layer whose CRS metadata will be inspected."""

    uri: str
    layer: str | None = None

    def __post_init__(self) -> None:
        if not self.uri.strip():
            raise ValueError("Dataset URI must not be empty")

    @property
    def identifier(self) -> str:
        """Return a stable human-readable dataset identifier."""
        return f"{self.uri}:{self.layer}" if self.layer else self.uri


@dataclass(frozen=True, slots=True)
class CrsMetadata:
    """Normalized CRS metadata independent from a specific projection library."""

    canonical_wkt: str
    display_name: str
    authority: str | None = None

    def __post_init__(self) -> None:
        if not self.canonical_wkt.strip():
            raise ValueError("Canonical CRS WKT must not be empty")
        if not self.display_name.strip():
            raise ValueError("CRS display name must not be empty")


@dataclass(frozen=True, slots=True)
class DatasetCrsMetadata:
    """CRS metadata read from one dataset; ``None`` means metadata is absent."""

    source: DatasetSource
    crs: CrsMetadata | None


class CrsAuditStatus(StrEnum):
    """Classification assigned to each dataset in a CRS audit."""

    CONSISTENT = "consistent"
    MISMATCH = "mismatch"
    MISSING = "missing"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class DatasetCrsAudit:
    """Audit outcome for one dataset."""

    source: DatasetSource
    status: CrsAuditStatus
    crs: CrsMetadata | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class CrsAuditResult:
    """Complete, serializable CRS consistency audit."""

    baseline: DatasetCrsMetadata | None
    datasets: tuple[DatasetCrsAudit, ...]

    @property
    def is_consistent(self) -> bool:
        """Return true only when every dataset has the baseline CRS."""
        return bool(self.datasets) and all(
            dataset.status is CrsAuditStatus.CONSISTENT for dataset in self.datasets
        )

    @property
    def mismatched_datasets(self) -> tuple[DatasetCrsAudit, ...]:
        """Return only datasets whose valid CRS differs from the baseline."""
        return tuple(
            dataset for dataset in self.datasets if dataset.status is CrsAuditStatus.MISMATCH
        )
