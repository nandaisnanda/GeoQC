"""Spawn-safe process pool with deterministic parent-side aggregation."""

import multiprocessing
import time
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import TypeVar

from geoqc.application.parallel.models import ParallelProgress, ParallelTask
from geoqc.application.parallel.scheduler import TaskScheduler
from geoqc.domain.models import BatchItemResult, BatchItemStatus, BatchResult

ResultT = TypeVar("ResultT")
Worker = Callable[[Path], ResultT]
ProgressObserver = Callable[[ParallelProgress], None]
Clock = Callable[[], float]


class ParallelBatchExecutor:
    """Execute independent datasets while preserving source order exactly."""

    def __init__(
        self,
        scheduler: TaskScheduler | None = None,
        *,
        clock: Clock = time.monotonic,
    ) -> None:
        self._scheduler = scheduler or TaskScheduler()
        self._clock = clock

    def run(
        self,
        sources: Iterable[Path],
        worker: Worker[ResultT],
        *,
        requested_workers: int | None = None,
        available_memory: int | None = None,
        multiprocessing_safe: bool = True,
        progress: ProgressObserver | None = None,
    ) -> BatchResult[ResultT]:
        tasks = self._scheduler.schedule(sources)
        worker_count = self._scheduler.worker_count(
            len(tasks),
            available_memory=available_memory,
            requested_workers=requested_workers,
            multiprocessing_safe=multiprocessing_safe,
        )
        started = self._clock()
        self._notify(progress, self._snapshot(0, len(tasks), tasks, None, started))
        if not tasks:
            return BatchResult()
        if worker_count == 1:
            return self._run_serial(tasks, worker, started, progress)
        return self._run_pool(tasks, worker, worker_count, started, progress)

    def _run_serial(
        self,
        tasks: tuple[ParallelTask, ...],
        worker: Worker[ResultT],
        started: float,
        progress: ProgressObserver | None,
    ) -> BatchResult[ResultT]:
        outcomes: dict[int, BatchItemResult[ResultT]] = {}
        for task in tasks:
            outcome = self._execute(task, worker)
            outcomes[task.sequence] = outcome
            pending = tuple(item for item in tasks if item.sequence not in outcomes)
            self._notify(
                progress,
                self._snapshot(len(outcomes), len(tasks), pending, outcome, started),
            )
        return self._ordered(outcomes)

    def _run_pool(
        self,
        tasks: tuple[ParallelTask, ...],
        worker: Worker[ResultT],
        worker_count: int,
        started: float,
        progress: ProgressObserver | None,
    ) -> BatchResult[ResultT]:
        outcomes: dict[int, BatchItemResult[ResultT]] = {}
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=worker_count, mp_context=context) as pool:
            futures: dict[Future[ResultT], ParallelTask] = {
                pool.submit(worker, task.source): task for task in tasks
            }
            try:
                for future in as_completed(futures):
                    task = futures[future]
                    outcome = self._from_future(task, future)
                    outcomes[task.sequence] = outcome
                    pending = tuple(item for item in tasks if item.sequence not in outcomes)
                    self._notify(
                        progress,
                        self._snapshot(len(outcomes), len(tasks), pending, outcome, started),
                    )
            except KeyboardInterrupt:
                for future in futures:
                    future.cancel()
                pool.shutdown(wait=False, cancel_futures=True)
                raise
        return self._ordered(outcomes)

    @staticmethod
    def _execute(task: ParallelTask, worker: Worker[ResultT]) -> BatchItemResult[ResultT]:
        try:
            return BatchItemResult(
                source=str(task.source),
                status=BatchItemStatus.SUCCEEDED,
                value=worker(task.source),
            )
        except Exception as error:
            return BatchItemResult(
                source=str(task.source),
                status=BatchItemStatus.FAILED,
                error=f"{type(error).__name__}: {error}",
            )

    @staticmethod
    def _from_future(task: ParallelTask, future: Future[ResultT]) -> BatchItemResult[ResultT]:
        try:
            return BatchItemResult(
                source=str(task.source),
                status=BatchItemStatus.SUCCEEDED,
                value=future.result(),
            )
        except Exception as error:
            return BatchItemResult(
                source=str(task.source),
                status=BatchItemStatus.FAILED,
                error=f"{type(error).__name__}: {error}",
            )

    def _snapshot(
        self,
        completed: int,
        total: int,
        pending: tuple[ParallelTask, ...],
        outcome: BatchItemResult[ResultT] | None,
        started: float = 0.0,
    ) -> ParallelProgress:
        elapsed = max(0.0, self._clock() - started)
        remaining = len(pending)
        eta = elapsed / completed * remaining if completed else None
        source = outcome.source if outcome is not None else None
        status = outcome.status if outcome is not None else None
        return ParallelProgress(
            completed=completed,
            total=total,
            current_sources=tuple(str(task.source) for task in pending),
            source=source,
            status=status,
            elapsed_seconds=elapsed,
            estimated_seconds=eta,
        )

    @staticmethod
    def _ordered(outcomes: dict[int, BatchItemResult[ResultT]]) -> BatchResult[ResultT]:
        return BatchResult(tuple(outcomes[index] for index in sorted(outcomes)))

    @staticmethod
    def _notify(observer: ProgressObserver | None, event: ParallelProgress) -> None:
        if observer is not None:
            observer(event)
