"""Domain-specific exceptions."""


class GeoQCError(Exception):
    """Base exception for errors expressed by the GeoQC domain."""


class DatasetMetadataReadError(GeoQCError):
    """Raised when metadata cannot be read or interpreted for one dataset."""

    def __init__(self, source: str, reason: str) -> None:
        self.source = source
        self.reason = reason
        super().__init__(f"Cannot read metadata for {source!r}: {reason}")


class StreamingError(GeoQCError):
    """Base exception for bounded dataset processing failures."""


class UnsupportedDatasetFormatError(StreamingError):
    """Raised when no registered reader supports a dataset."""


class CorruptDatasetError(StreamingError):
    """Raised when a supported dataset cannot be decoded safely."""


class DatasetEncodingError(StreamingError):
    """Raised when source attributes cannot be decoded."""


class MissingCRSError(StreamingError):
    """Raised when an audit requiring CRS receives no CRS metadata."""

    def __init__(self, source: str, layer: str | None) -> None:
        super().__init__(f"Dataset {source!r} layer {layer!r} has no CRS")


class EmptyLayerError(StreamingError):
    """Raised when a selected layer contains no features."""

    def __init__(self, source: str, layer: str | None) -> None:
        super().__init__(f"Dataset {source!r} layer {layer!r} is empty")


class StreamingMemoryError(StreamingError):
    """Raised when a bounded chunk still cannot be allocated."""

    def __init__(self, source: str, chunk_size: int) -> None:
        super().__init__(f"Cannot allocate a {chunk_size}-feature chunk for {source!r}")


class DatumTransformationError(GeoQCError):
    """Raised when a datum transformation cannot be inspected safely."""


class RuleEngineError(GeoQCError):
    """Base exception raised by rule-engine operations."""


class DuplicateRuleError(RuleEngineError):
    """Raised when two registered rules use the same identifier."""


class UnknownRuleError(RuleEngineError):
    """Raised when a requested rule identifier is not registered."""


class InvalidRuleResultError(RuleEngineError):
    """Raised when a rule returns a result for a different rule identifier."""


class RuleExecutionError(RuleEngineError):
    """Wrap an unexpected exception raised while executing a rule."""

    def __init__(self, rule_id: str, cause: Exception) -> None:
        self.rule_id = rule_id
        self.cause = cause
        super().__init__(f"Rule {rule_id!r} failed: {cause}")
