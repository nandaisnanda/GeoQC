import pytest

from geoqc.domain.models import (
    BatchItemResult,
    BatchItemStatus,
    BatchProgress,
    BatchResult,
)


def test_batch_result_summarizes_mixed_outcomes() -> None:
    result = BatchResult(
        items=(
            BatchItemResult(source="roads.gpkg", status=BatchItemStatus.SUCCEEDED, value=3),
            BatchItemResult(
                source="broken.shp",
                status=BatchItemStatus.FAILED,
                error="ValueError: unreadable",
            ),
        )
    )

    assert result.total == 2
    assert result.succeeded == 1
    assert result.failed == 1
    assert not result.is_successful


def test_empty_batch_is_successful() -> None:
    result = BatchResult[object]()

    assert result.total == 0
    assert result.is_successful


def test_batch_item_rejects_empty_source() -> None:
    with pytest.raises(ValueError, match="source"):
        BatchItemResult(source=" ", status=BatchItemStatus.SUCCEEDED)


def test_batch_item_rejects_error_on_success() -> None:
    with pytest.raises(ValueError, match="successful"):
        BatchItemResult(
            source="roads.gpkg",
            status=BatchItemStatus.SUCCEEDED,
            error="unexpected",
        )


def test_batch_item_requires_error_on_failure() -> None:
    with pytest.raises(ValueError, match="failed"):
        BatchItemResult(source="roads.gpkg", status=BatchItemStatus.FAILED)


@pytest.mark.parametrize(("completed", "total"), [(-1, 1), (2, 1), (0, -1)])
def test_batch_progress_rejects_out_of_range_counts(completed: int, total: int) -> None:
    with pytest.raises(ValueError, match="progress"):
        BatchProgress(completed=completed, total=total)


def test_batch_progress_rejects_item_on_initial_event() -> None:
    with pytest.raises(ValueError, match="initial"):
        BatchProgress(completed=0, total=1, source="roads.gpkg")


def test_batch_progress_requires_item_on_completion_event() -> None:
    with pytest.raises(ValueError, match="identify"):
        BatchProgress(completed=1, total=1)
