"""Public application-layer building blocks for bounded dataset processing."""

from geoqc.application.streaming.collector import RuleResultCollector
from geoqc.application.streaming.engine import StreamingEngine
from geoqc.application.streaming.models import (
    DatasetMetadata,
    DatasetSource,
    FeatureChunk,
    ScanOptions,
    ScanPredicate,
    StreamingConfig,
    StreamingResult,
)
from geoqc.application.streaming.processor import RuleEngineChunkProcessor

__all__ = [
    "DatasetMetadata",
    "DatasetSource",
    "FeatureChunk",
    "RuleEngineChunkProcessor",
    "RuleResultCollector",
    "ScanOptions",
    "ScanPredicate",
    "StreamingConfig",
    "StreamingEngine",
    "StreamingResult",
]
