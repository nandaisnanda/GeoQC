"""Bounded, process-local API metrics without user-controlled labels."""

from collections import Counter, defaultdict
from threading import Lock

_ROUTES = frozenset(
    {
        "/api/geometry/validate",
        "/api/geometry/validate-shapefile",
        "/api/geometry/repair",
        "/api/spatial/duplicates",
        "/api/spatial/compare",
        "/api/spatial/conflicts",
        "/api/repairs/prioritize",
        "/api/jobs/geometry/validate",
        "/api/jobs/{job_id}",
        "/metrics",
    }
)


class MetricsRegistry:
    """Thread-safe counters and duration sums with a fixed label vocabulary."""

    def __init__(self) -> None:
        self._requests: Counter[tuple[str, str, str]] = Counter()
        self._duration: dict[tuple[str, str], float] = defaultdict(float)
        self._events: Counter[str] = Counter()
        self._jobs: Counter[str] = Counter()
        self._lock = Lock()

    @staticmethod
    def route_label(route: str) -> str:
        return route if route in _ROUTES else "other"

    def observe_request(self, method: str, route: str, status: int, duration: float) -> None:
        normalized = self.route_label(route)
        with self._lock:
            self._requests[(method, normalized, str(status))] += 1
            self._duration[(method, normalized)] += duration

    def event(self, name: str) -> None:
        if name not in {"upload_rejected", "audit_succeeded", "audit_failed"}:
            raise ValueError("unsupported metric event")
        with self._lock:
            self._events[name] += 1

    def job_state(self, state: str) -> None:
        if state not in {"queued", "running", "succeeded", "failed"}:
            raise ValueError("unsupported job state")
        with self._lock:
            self._jobs[state] += 1

    def render(self) -> str:
        """Render a small Prometheus-compatible text exposition."""
        with self._lock:
            lines = ["# TYPE geoqc_http_requests_total counter"]
            for (method, route, status), count in sorted(self._requests.items()):
                lines.append(
                    f'geoqc_http_requests_total{{method="{method}",route="{route}",'
                    f'status="{status}"}} {count}'
                )
            lines.append("# TYPE geoqc_http_request_duration_seconds_sum counter")
            for (method, route), duration in sorted(self._duration.items()):
                lines.append(
                    f'geoqc_http_request_duration_seconds_sum{{method="{method}",'
                    f'route="{route}"}} {duration:.9f}'
                )
            for name, value in sorted(self._events.items()):
                lines.append(f"geoqc_{name}_total {value}")
            for state, value in sorted(self._jobs.items()):
                lines.append(f'geoqc_jobs_total{{state="{state}"}} {value}')
        return "\n".join(lines) + "\n"
