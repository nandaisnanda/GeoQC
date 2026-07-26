from io import StringIO

import pytest

from geoqc.domain.models import BatchItemStatus, BatchProgress
from geoqc.interfaces.cli.progress import ConsoleProgressIndicator


def test_console_progress_indicator_renders_initial_and_completed_states() -> None:
    stream = StringIO()
    indicator = ConsoleProgressIndicator(stream=stream, width=10)

    indicator(BatchProgress(completed=0, total=2))
    indicator(
        BatchProgress(
            completed=1,
            total=2,
            source="roads.gpkg",
            status=BatchItemStatus.SUCCEEDED,
        )
    )
    indicator(
        BatchProgress(
            completed=2,
            total=2,
            source="broken.shp",
            status=BatchItemStatus.FAILED,
        )
    )

    assert stream.getvalue().splitlines() == [
        "[----------] 0/2 Discovering datasets",
        "[#####-----] 1/2 succeeded: roads.gpkg",
        "[##########] 2/2 failed: broken.shp",
    ]


def test_console_progress_indicator_handles_empty_batch() -> None:
    stream = StringIO()

    ConsoleProgressIndicator(stream=stream, width=4)(BatchProgress(completed=0, total=0))

    assert stream.getvalue() == "[####] 0/0 Discovering datasets\n"


def test_console_progress_indicator_rejects_non_positive_width() -> None:
    with pytest.raises(ValueError, match="positive"):
        ConsoleProgressIndicator(width=0)
