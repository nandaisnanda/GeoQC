from pathlib import Path

import pytest

from geoqc.application.services import BatchProcessor
from geoqc.domain.models import BatchItemStatus, BatchProgress


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def test_discover_accepts_multiple_files_and_folder_with_stable_deduplication(
    tmp_path: Path,
) -> None:
    roads = _touch(tmp_path / "roads.GPKG")
    parcels = _touch(tmp_path / "parcels.shp")
    _touch(tmp_path / "notes.txt")
    processor = BatchProcessor[str](lambda path: path.name)

    sources = processor.discover([roads, tmp_path, parcels])

    assert sources == tuple(
        sorted(
            (parcels.resolve(), roads.resolve()),
            key=lambda item: str(item).casefold(),
        )
    )


def test_discover_only_descends_into_nested_folders_when_recursive(tmp_path: Path) -> None:
    root_file = _touch(tmp_path / "root.geojson")
    nested_file = _touch(tmp_path / "nested" / "child.gpkg")
    processor = BatchProcessor[str](lambda path: path.name)

    assert processor.discover([tmp_path]) == (root_file.resolve(),)
    assert processor.discover([tmp_path], recursive=True) == tuple(
        sorted(
            (nested_file.resolve(), root_file.resolve()),
            key=lambda item: str(item).casefold(),
        )
    )


def test_custom_suffixes_are_normalized(tmp_path: Path) -> None:
    dataset = _touch(tmp_path / "survey.CSV")
    processor = BatchProcessor[str](lambda path: path.name, supported_suffixes=[" csv "])

    assert processor.discover([tmp_path]) == (dataset.resolve(),)


def test_process_continues_after_failure_and_emits_progress_for_every_item(
    tmp_path: Path,
) -> None:
    good = _touch(tmp_path / "a.gpkg")
    broken = _touch(tmp_path / "b.gpkg")
    events: list[BatchProgress] = []

    def process(path: Path) -> str:
        if path == broken.resolve():
            raise RuntimeError("cannot read dataset")
        return path.stem.upper()

    result = BatchProcessor(process).process([tmp_path], progress=events.append)

    assert result.total == 2
    assert result.succeeded == 1
    assert result.failed == 1
    assert result.items[0].source == str(good.resolve())
    assert result.items[0].value == "A"
    assert result.items[1].status is BatchItemStatus.FAILED
    assert result.items[1].error == "RuntimeError: cannot read dataset"
    assert [(event.completed, event.total, event.status) for event in events] == [
        (0, 2, None),
        (1, 2, BatchItemStatus.SUCCEEDED),
        (2, 2, BatchItemStatus.FAILED),
    ]


def test_process_empty_folder_emits_completed_empty_progress(tmp_path: Path) -> None:
    events: list[BatchProgress] = []

    result = BatchProcessor[str](lambda path: path.name).process([tmp_path], progress=events.append)

    assert result.is_successful
    assert events == [BatchProgress(completed=0, total=0)]


def test_discover_rejects_missing_and_explicitly_unsupported_inputs(tmp_path: Path) -> None:
    processor = BatchProcessor[str](lambda path: path.name)

    with pytest.raises(FileNotFoundError, match="does not exist"):
        processor.discover([tmp_path / "missing.gpkg"])

    unsupported = _touch(tmp_path / "notes.txt")
    with pytest.raises(ValueError, match="Unsupported dataset"):
        processor.discover([unsupported])


@pytest.mark.parametrize("suffixes", [[], [" "]])
def test_processor_rejects_invalid_suffix_configuration(suffixes: list[str]) -> None:
    with pytest.raises(ValueError, match="suffix"):
        BatchProcessor[str](lambda path: path.name, supported_suffixes=suffixes)
