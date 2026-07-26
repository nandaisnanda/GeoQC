"""Tests for framework-independent attribute schema models."""

import pytest

from geoqc.domain.models import AttributeColumnSchema, AttributeDataType, AttributeSchema


def test_attribute_schema_requires_unique_columns() -> None:
    """Ambiguous duplicate column declarations are rejected."""
    column = AttributeColumnSchema("id", AttributeDataType.INTEGER)

    with pytest.raises(ValueError, match="unique"):
        AttributeSchema((column, column), id_column="id")


def test_attribute_schema_requires_declared_id_column() -> None:
    """The uniqueness key must belong to the expected schema."""
    with pytest.raises(ValueError, match="declared"):
        AttributeSchema(
            (AttributeColumnSchema("name", AttributeDataType.STRING),),
            id_column="id",
        )
