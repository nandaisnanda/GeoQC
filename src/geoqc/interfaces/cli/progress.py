"""Terminal progress indicator for batch-processing events."""

import sys
from dataclasses import dataclass
from typing import TextIO

from geoqc.application.parallel import ParallelProgress
from geoqc.domain.models import BatchProgress


@dataclass(slots=True)
class ConsoleProgressIndicator:
    """Render deterministic progress lines without coupling the use case to Typer."""

    stream: TextIO = sys.stderr
    width: int = 20

    def __post_init__(self) -> None:
        if self.width <= 0:
            raise ValueError("progress indicator width must be positive")

    def __call__(self, event: BatchProgress) -> None:
        ratio = event.completed / event.total if event.total else 1.0
        filled = round(ratio * self.width)
        bar = f"[{'#' * filled}{'-' * (self.width - filled)}]"
        detail = "Discovering datasets"
        if event.source is not None and event.status is not None:
            detail = f"{event.status.value}: {event.source}"
        print(f"{bar} {event.completed}/{event.total} {detail}", file=self.stream, flush=True)


@dataclass(slots=True)
class ParallelConsoleProgress:
    """Render parent-owned monitoring for parallel dataset audits."""

    stream: TextIO = sys.stderr

    def __call__(self, event: ParallelProgress) -> None:
        current = ", ".join(event.current_sources[:3]) or "-"
        if len(event.current_sources) > 3:
            current = f"{current}, +{len(event.current_sources) - 3} more"
        eta = (
            f"{event.estimated_seconds:.1f}s"
            if event.estimated_seconds is not None
            else "calculating"
        )
        print(
            f"Progress: {event.completed}/{event.total} | Current File(s): {current} | "
            f"Completed: {event.completed} | Remaining: {event.remaining} | "
            f"Estimated Time: {eta}",
            file=self.stream,
            flush=True,
        )
