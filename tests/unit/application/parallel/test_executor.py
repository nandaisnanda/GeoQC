import time
from pathlib import Path

from geoqc.application.parallel import ParallelBatchExecutor, ParallelProgress
from geoqc.domain.models import BatchItemStatus


def _delayed_name(path: Path) -> str:
    time.sleep(0.01 * (4 - int(path.stem)))
    return path.name


def _sometimes_fails(path: Path) -> str:
    if path.stem == "2":
        raise ValueError("broken")
    return path.name


def test_process_pool_results_are_deterministic_despite_completion_order() -> None:
    sources = tuple(Path(f"{index}.gpkg") for index in range(1, 4))

    result = ParallelBatchExecutor().run(sources, _delayed_name, requested_workers=2)

    assert [item.value for item in result.items] == ["1.gpkg", "2.gpkg", "3.gpkg"]


def test_worker_failure_is_isolated_and_progress_reaches_total() -> None:
    events: list[ParallelProgress] = []
    sources = tuple(Path(f"{index}.gpkg") for index in range(1, 4))

    result = ParallelBatchExecutor().run(
        sources,
        _sometimes_fails,
        requested_workers=2,
        progress=events.append,
    )

    assert [item.status for item in result.items] == [
        BatchItemStatus.SUCCEEDED,
        BatchItemStatus.FAILED,
        BatchItemStatus.SUCCEEDED,
    ]
    assert result.items[1].error == "ValueError: broken"
    assert events[0].completed == 0
    assert events[-1].completed == events[-1].total == 3


def test_serial_fallback_has_identical_outcome() -> None:
    sources = tuple(Path(f"{index}.gpkg") for index in range(1, 4))
    executor = ParallelBatchExecutor()

    serial = executor.run(sources, _sometimes_fails, multiprocessing_safe=False)
    parallel = executor.run(sources, _sometimes_fails, requested_workers=2)

    assert serial == parallel
