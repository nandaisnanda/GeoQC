"""Compare disabled and enabled recorder overhead outside the test suite."""

import argparse
import statistics
import time

from geoqc.application.benchmarking import BenchmarkContext, NoOpBenchmarkRecorder
from geoqc.infrastructure.benchmarking import ProcessBenchmarkRecorder


def operation(duration: float) -> tuple[int, int, str]:
    time.sleep(duration)
    return 1, 1, "synthetic"


def elapsed(recorder: object, iterations: int, duration: float) -> float:
    context = BenchmarkContext("synthetic", chunk_size=1, worker_count=1)
    start = time.perf_counter()
    for _ in range(iterations):
        recorder.measure(lambda: operation(duration), context, lambda result: result)  # type: ignore[attr-defined]
    return time.perf_counter() - start


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--duration", type=float, default=0.02)
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()
    disabled = [
        elapsed(NoOpBenchmarkRecorder(), args.iterations, args.duration) for _ in range(args.rounds)
    ]
    enabled = [
        elapsed(ProcessBenchmarkRecorder(), args.iterations, args.duration)
        for _ in range(args.rounds)
    ]
    baseline = statistics.median(disabled)
    measured = statistics.median(enabled)
    overhead = (measured / baseline - 1.0) * 100.0 if baseline else 0.0
    print(f"disabled={baseline:.6f}s enabled={measured:.6f}s overhead={overhead:.2f}%")


if __name__ == "__main__":
    main()
