"""Process-local fixed-window rate limiting with injectable time and storage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import ceil
from threading import Lock
from time import monotonic


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int
    remaining: int


class InMemoryRateLimitStorage:
    """Thread-safe process-local counter storage."""

    def __init__(self) -> None:
        self._values: dict[str, tuple[float, int]] = {}
        self._lock = Lock()

    def increment(self, key: str, now: float, window_seconds: int) -> tuple[float, int]:
        with self._lock:
            start, count = self._values.get(key, (now, 0))
            if now - start >= window_seconds:
                start, count = now, 0
            count += 1
            self._values[key] = (start, count)
            return start, count


class FixedWindowRateLimiter:
    """Testable rate limiter; storage is intentionally local to one process."""

    def __init__(
        self,
        storage: InMemoryRateLimitStorage | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._storage = storage or InMemoryRateLimitStorage()
        self._clock = clock

    def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        now = self._clock()
        start, count = self._storage.increment(key, now, window_seconds)
        retry = max(1, ceil(window_seconds - (now - start)))
        return RateLimitDecision(count <= limit, retry, max(0, limit - count))
