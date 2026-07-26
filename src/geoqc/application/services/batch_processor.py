"""Discover local GIS datasets and process them as an observable batch."""

from collections.abc import Callable, Iterable
from pathlib import Path

from geoqc.domain.models import (
    BatchItemResult,
    BatchItemStatus,
    BatchProgress,
    BatchResult,
)

type DatasetProcessor[ResultT] = Callable[[Path], ResultT]
ProgressObserver = Callable[[BatchProgress], None]

DEFAULT_DATASET_SUFFIXES = frozenset(
    {".fgb", ".geojson", ".gml", ".gpkg", ".json", ".kml", ".parquet", ".shp"}
)


class BatchProcessor[ResultT]:
    """Run one injected processor for files and folders without failing fast."""

    def __init__(
        self,
        processor: DatasetProcessor[ResultT],
        *,
        supported_suffixes: Iterable[str] = DEFAULT_DATASET_SUFFIXES,
    ) -> None:
        self._processor = processor
        self._supported_suffixes = frozenset(
            self._normalize_suffix(item) for item in supported_suffixes
        )
        if not self._supported_suffixes:
            raise ValueError("supported_suffixes must not be empty")

    def discover(
        self, inputs: Iterable[str | Path], *, recursive: bool = False
    ) -> tuple[Path, ...]:
        """Expand files and folders into unique supported datasets in stable order."""
        discovered: set[Path] = set()
        for raw_input in inputs:
            path = Path(raw_input).expanduser()
            if not path.exists():
                raise FileNotFoundError(f"Batch input does not exist: {path}")
            if path.is_file():
                if not self._is_supported(path):
                    raise ValueError(f"Unsupported dataset file: {path}")
                discovered.add(path.resolve())
                continue
            if not path.is_dir():
                raise ValueError(f"Batch input is neither a file nor a directory: {path}")

            candidates = path.rglob("*") if recursive else path.glob("*")
            discovered.update(
                candidate.resolve()
                for candidate in candidates
                if candidate.is_file() and self._is_supported(candidate)
            )
        return tuple(sorted(discovered, key=lambda item: str(item).casefold()))

    def process(
        self,
        inputs: Iterable[str | Path],
        *,
        recursive: bool = False,
        progress: ProgressObserver | None = None,
    ) -> BatchResult[ResultT]:
        """Discover and process all datasets, reporting failures per item."""
        sources = self.discover(inputs, recursive=recursive)
        self._notify(progress, BatchProgress(completed=0, total=len(sources)))
        items: list[BatchItemResult[ResultT]] = []
        for completed, source in enumerate(sources, start=1):
            try:
                item = BatchItemResult(
                    source=str(source),
                    status=BatchItemStatus.SUCCEEDED,
                    value=self._processor(source),
                )
            except Exception as error:
                item = BatchItemResult[ResultT](
                    source=str(source),
                    status=BatchItemStatus.FAILED,
                    error=f"{type(error).__name__}: {error}",
                )
            items.append(item)
            self._notify(
                progress,
                BatchProgress(
                    completed=completed,
                    total=len(sources),
                    source=str(source),
                    status=item.status,
                ),
            )
        return BatchResult(items=tuple(items))

    def _is_supported(self, path: Path) -> bool:
        return path.suffix.casefold() in self._supported_suffixes

    @staticmethod
    def _normalize_suffix(suffix: str) -> str:
        normalized = suffix.strip().casefold()
        if not normalized:
            raise ValueError("dataset suffix must not be empty")
        return normalized if normalized.startswith(".") else f".{normalized}"

    @staticmethod
    def _notify(observer: ProgressObserver | None, event: BatchProgress) -> None:
        if observer is not None:
            observer(event)
