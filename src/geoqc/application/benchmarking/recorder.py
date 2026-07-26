"""Benchmark recording contracts and disabled implementation."""

from collections.abc import Callable
from typing import Protocol, TypeVar

from geoqc.application.benchmarking.models import BenchmarkContext, BenchmarkMetrics

ResultT = TypeVar("ResultT")


class BenchmarkRecorder(Protocol):
    """Measure a callable and derive audit-specific metrics from its value."""

    def measure(
        self,
        operation: Callable[[], ResultT],
        context: BenchmarkContext,
        describe: Callable[[ResultT], tuple[int, int, str]],
    ) -> tuple[ResultT, BenchmarkMetrics | None]: ...


class NoOpBenchmarkRecorder:
    """Disabled recorder with no clocks, probes, sampling, or allocations."""

    def measure(
        self,
        operation: Callable[[], ResultT],
        context: BenchmarkContext,
        describe: Callable[[ResultT], tuple[int, int, str]],
    ) -> tuple[ResultT, None]:
        del context, describe
        return operation(), None
