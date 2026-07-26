"""Low-overhead process-local resource benchmark recorder."""

import mmap
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar, cast

from geoqc.application.benchmarking import BenchmarkContext, BenchmarkMetrics

ResultT = TypeVar("ResultT")
Clock = Callable[[], float]
MemoryProbe = Callable[[], tuple[int, int]]


def process_memory() -> tuple[int, int]:
    """Return current RSS and process peak RSS in bytes without third-party packages."""
    if sys.platform == "win32":
        return _windows_process_memory()
    try:
        import resource

        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if sys.platform != "darwin":
            peak *= 1024
    except (ImportError, OSError):
        peak = 0
    current = _proc_current_rss() or peak
    return max(0, current), max(0, peak, current)


def _proc_current_rss() -> int:
    try:
        statm = Path("/proc/self/statm").read_text(encoding="ascii").split()
        return int(statm[1]) * mmap.PAGESIZE
    except (OSError, ValueError, IndexError, AttributeError):
        return 0


def _windows_process_memory() -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    ctypes_api = cast(Any, ctypes)
    kernel32 = ctypes_api.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes_api.WinDLL("psapi", use_last_error=True)
    process = kernel32.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
        return 0, 0
    return int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize)


@dataclass(slots=True)
class ProcessBenchmarkRecorder:
    """Take two clock and memory snapshots around one complete audit."""

    wall_clock: Clock = time.perf_counter
    cpu_clock: Clock = time.process_time
    memory_probe: MemoryProbe = process_memory

    def measure(
        self,
        operation: Callable[[], ResultT],
        context: BenchmarkContext,
        describe: Callable[[ResultT], tuple[int, int, str]],
    ) -> tuple[ResultT, BenchmarkMetrics]:
        memory_before, peak_before = self.memory_probe()
        cpu_before = self.cpu_clock()
        wall_before = self.wall_clock()
        result = operation()
        runtime = max(0.0, self.wall_clock() - wall_before)
        cpu_time = max(0.0, self.cpu_clock() - cpu_before)
        memory_after, peak_after = self.memory_probe()
        feature_count, geometry_count, engine = describe(result)
        return result, BenchmarkMetrics(
            source=context.source,
            runtime_seconds=runtime,
            cpu_time_seconds=cpu_time,
            cpu_usage_percent=(cpu_time / runtime * 100.0 if runtime else 0.0),
            memory_usage_bytes=max(0, memory_after - memory_before),
            peak_memory_bytes=max(peak_before, peak_after, memory_after),
            feature_count=feature_count,
            geometry_count=geometry_count,
            rule_count=context.rule_count,
            engine=engine,
            chunk_size=context.chunk_size,
            worker_count=context.worker_count,
        )
