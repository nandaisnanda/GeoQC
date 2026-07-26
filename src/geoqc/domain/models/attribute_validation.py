"""Framework-independent schema and results for attribute quality scans."""

from dataclasses import dataclass
from enum import StrEnum


class AttributeDataType(StrEnum):
    """Logical data types supported by an attribute schema."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATETIME = "datetime"


class AttributeIssueType(StrEnum):
    """Stable categories of attribute quality problems."""

    NULL_VALUE = "null_value"
    DUPLICATE_ID = "duplicate_id"
    MISSING_COLUMN = "missing_column"
    INVALID_DATA_TYPE = "invalid_data_type"
    SCHEMA_DRIFT = "schema_drift"


@dataclass(frozen=True, slots=True)
class AttributeColumnSchema:
    """Expected logical type and nullability for one column."""

    name: str
    data_type: AttributeDataType
    nullable: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("column name must not be blank")


@dataclass(frozen=True, slots=True)
class AttributeSchema:
    """Expected table schema and the column used as its unique identifier."""

    columns: tuple[AttributeColumnSchema, ...]
    id_column: str

    def __post_init__(self) -> None:
        names = tuple(column.name for column in self.columns)
        if not self.id_column.strip():
            raise ValueError("id_column must not be blank")
        if len(names) != len(set(names)):
            raise ValueError("schema column names must be unique")
        if self.id_column not in names:
            raise ValueError("id_column must be declared in columns")


@dataclass(frozen=True, slots=True)
class AttributeValidationIssue:
    """One attribute problem and its optional column and row positions."""

    issue_type: AttributeIssueType
    message: str
    column: str | None = None
    row_positions: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class AttributeValidationResult:
    """Complete attribute scan result for one table."""

    row_count: int
    issues: tuple[AttributeValidationIssue, ...]

    @property
    def is_valid(self) -> bool:
        """Return whether the table conforms to its expected schema."""
        return not self.issues

    def has_issue(self, issue_type: AttributeIssueType) -> bool:
        """Return whether a particular issue category was detected."""
        return any(issue.issue_type is issue_type for issue in self.issues)
