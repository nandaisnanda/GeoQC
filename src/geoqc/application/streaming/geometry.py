"""Streaming geometry audit processor and bounded result collector."""

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GeometryFinding:
    """One feature's normalized geometry issues."""

    feature_index: int
    issues: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class GeometryChunkResult:
    feature_count: int
    invalid_feature_count: int
    issue_counts: Counter[str]
    findings: tuple[GeometryFinding, ...]


@dataclass(frozen=True, slots=True)
class GeometryAuditResult:
    feature_count: int
    invalid_feature_count: int
    issue_counts: dict[str, int]
    findings: tuple[GeometryFinding, ...]


class GeometryResultCollector:
    """Merge counts while retaining only a bounded findings prefix."""

    def __init__(self, maximum_findings: int = 1_000) -> None:
        self._maximum_findings = maximum_findings
        self._feature_count = 0
        self._invalid_count = 0
        self._counts: Counter[str] = Counter()
        self._findings: list[GeometryFinding] = []

    def add(self, result: object) -> None:
        if not isinstance(result, GeometryChunkResult):
            raise TypeError("GeometryResultCollector expects GeometryChunkResult values")
        self._feature_count += result.feature_count
        self._invalid_count += result.invalid_feature_count
        self._counts.update(result.issue_counts)
        remaining = self._maximum_findings - len(self._findings)
        if remaining > 0:
            self._findings.extend(result.findings[:remaining])

    def finish(self) -> GeometryAuditResult:
        return GeometryAuditResult(
            self._feature_count,
            self._invalid_count,
            dict(sorted(self._counts.items())),
            tuple(self._findings),
        )
