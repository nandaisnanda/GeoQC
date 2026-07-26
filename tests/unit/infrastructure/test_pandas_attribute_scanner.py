"""Unit tests for pandas-based attribute validation."""

import pandas as pd
import pytest

from geoqc.domain.models import (
    AttributeColumnSchema,
    AttributeDataType,
    AttributeIssueType,
    AttributeSchema,
)
from geoqc.infrastructure.gis.pandas_attribute_scanner import PandasAttributeScanner


@pytest.fixture
def schema() -> AttributeSchema:
    """Return a representative strict attribute schema."""
    return AttributeSchema(
        columns=(
            AttributeColumnSchema("id", AttributeDataType.INTEGER, nullable=False),
            AttributeColumnSchema("name", AttributeDataType.STRING, nullable=False),
            AttributeColumnSchema("score", AttributeDataType.FLOAT),
            AttributeColumnSchema("active", AttributeDataType.BOOLEAN),
            AttributeColumnSchema("created_at", AttributeDataType.DATETIME),
        ),
        id_column="id",
    )


def test_accepts_conforming_attributes(schema: AttributeSchema) -> None:
    """A table matching columns, types, nullability, and ID uniqueness is valid."""
    frame = pd.DataFrame(
        {
            "id": [1, 2],
            "name": ["alpha", "beta"],
            "score": [1.5, None],
            "active": [True, False],
            "created_at": pd.to_datetime(["2026-01-01", "2026-01-02"]),
        }
    )

    result = PandasAttributeScanner().scan(frame, schema)

    assert result.is_valid
    assert result.row_count == 2


def test_detects_null_value_in_non_nullable_column(schema: AttributeSchema) -> None:
    """Null positions are reported only for non-nullable columns."""
    frame = pd.DataFrame({"id": [1, 2], "name": ["alpha", None]})

    result = PandasAttributeScanner().scan(frame, schema)

    issue = next(
        issue for issue in result.issues if issue.issue_type is AttributeIssueType.NULL_VALUE
    )
    assert issue.column == "name"
    assert issue.row_positions == (1,)


def test_detects_all_rows_with_duplicate_non_null_ids(schema: AttributeSchema) -> None:
    """Every occurrence of a repeated ID is identified; nulls are a separate issue."""
    frame = pd.DataFrame({"id": [7, 7, 8], "name": ["a", "b", "c"]})

    result = PandasAttributeScanner().scan(frame, schema)

    duplicate = next(
        issue for issue in result.issues if issue.issue_type is AttributeIssueType.DUPLICATE_ID
    )
    assert duplicate.row_positions == (0, 1)


def test_detects_missing_columns_and_schema_drift(schema: AttributeSchema) -> None:
    """Removed columns receive a specific issue plus an overall structural drift issue."""
    frame = pd.DataFrame({"id": [1], "name": ["a"], "legacy_code": ["x"]})

    result = PandasAttributeScanner().scan(frame, schema)

    missing_columns = {
        issue.column
        for issue in result.issues
        if issue.issue_type is AttributeIssueType.MISSING_COLUMN
    }
    assert missing_columns == {"score", "active", "created_at"}
    assert result.has_issue(AttributeIssueType.SCHEMA_DRIFT)


def test_detects_added_column_as_schema_drift(schema: AttributeSchema) -> None:
    """An unexpected column changes the schema even when expected fields remain present."""
    frame = pd.DataFrame(
        {
            "id": [1],
            "name": ["a"],
            "score": [1.0],
            "active": [True],
            "created_at": [pd.Timestamp("2026-01-01")],
            "unexpected": [10],
        }
    )

    result = PandasAttributeScanner().scan(frame, schema)

    drift = next(
        issue for issue in result.issues if issue.issue_type is AttributeIssueType.SCHEMA_DRIFT
    )
    assert "unexpected" in drift.message
    assert not result.has_issue(AttributeIssueType.MISSING_COLUMN)


def test_detects_invalid_logical_types_and_ignores_nulls(schema: AttributeSchema) -> None:
    """Mixed object columns are checked value-by-value using logical type rules."""
    frame = pd.DataFrame(
        {
            "id": [1, "2"],
            "name": ["a", 99],
            "score": [2, "high"],
            "active": [True, 1],
            "created_at": [pd.Timestamp("2026-01-01"), "yesterday"],
        }
    )

    result = PandasAttributeScanner().scan(frame, schema)

    invalid = {
        issue.column: issue.row_positions
        for issue in result.issues
        if issue.issue_type is AttributeIssueType.INVALID_DATA_TYPE
    }
    assert invalid == {
        "id": (1,),
        "name": (1,),
        "score": (1,),
        "active": (1,),
        "created_at": (1,),
    }


def test_rejects_non_dataframe_input(schema: AttributeSchema) -> None:
    """The adapter rejects unsupported containers explicitly."""
    with pytest.raises(TypeError, match="pandas DataFrame"):
        PandasAttributeScanner().scan([], schema)  # type: ignore[arg-type]
