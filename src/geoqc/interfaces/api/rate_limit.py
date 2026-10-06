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

    def __init__(self, *, max_entries: int = 10_000) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be greater than zero")
        self._values: dict[str, tuple[float, int]] = {}
        self._max_entries = max_entries
        self._lock = Lock()

    def increment(self, key: str, now: float, window_seconds: int) -> tuple[float, int]:
        with self._lock:
            self._cleanup_locked(now, window_seconds)
            if key not in self._values and len(self._values) >= self._max_entries:
                oldest = min(self._values, key=lambda item: (self._values[item][0], item))
                del self._values[oldest]
            start, count = self._values.get(key, (now, 0))
            if now - start >= window_seconds:
                start, count = now, 0
            count += 1
            self._values[key] = (start, count)
            return start, count

    def cleanup(self, now: float, window_seconds: int) -> int:
        """Remove expired windows and return the number of released identities."""
        with self._lock:
            return self._cleanup_locked(now, window_seconds)

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._values)

    def _cleanup_locked(self, now: float, window_seconds: int) -> int:
        expired = [
            key
            for key, (started, _count) in self._values.items()
            if now - started >= window_seconds
        ]
        for key in expired:
            del self._values[key]
        return len(expired)


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
