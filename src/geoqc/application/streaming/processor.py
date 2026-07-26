"""Adapters that send bounded chunks to the existing Rule Engine."""

from collections.abc import Callable, Sequence

from geoqc.application.streaming.models import DatasetMetadata, FeatureChunk
from geoqc.domain.rules.engine import RuleEngine
from geoqc.domain.rules.models import EngineResult


class RuleEngineChunkProcessor:
    """Execute existing registered rules against a chunk-derived context."""

    def __init__(
        self,
        engine: RuleEngine[object],
        context_factory: Callable[[FeatureChunk, DatasetMetadata], object],
        rule_ids: Sequence[str] | None = None,
    ) -> None:
        self._engine = engine
        self._context_factory = context_factory
        self._rule_ids = rule_ids

    def process(self, chunk: FeatureChunk, metadata: DatasetMetadata) -> EngineResult:
        return self._engine.execute(self._context_factory(chunk, metadata), rule_ids=self._rule_ids)
