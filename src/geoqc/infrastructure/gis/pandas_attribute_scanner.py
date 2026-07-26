"""Attribute validation adapter for pandas DataFrames."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from geoqc.domain.models import (
    AttributeDataType,
    AttributeIssueType,
    AttributeSchema,
    AttributeValidationIssue,
    AttributeValidationResult,
)

ValuePredicate = Callable[[Any], bool]


class PandasAttributeScanner:
    """Check tabular attributes against an explicit logical schema."""

    def scan(
        self,
        frame: pd.DataFrame,
        schema: AttributeSchema,
    ) -> AttributeValidationResult:
        """Return all detectable quality issues without failing fast."""
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("frame must be a pandas DataFrame")

        issues: list[AttributeValidationIssue] = []
        expected = {column.name: column for column in schema.columns}
        actual_names = {str(name) for name in frame.columns}
        expected_names = set(expected)
        missing = sorted(expected_names - actual_names)
        added = sorted(actual_names - expected_names)

        for name in missing:
            issues.append(
                AttributeValidationIssue(
                    AttributeIssueType.MISSING_COLUMN,
                    f"Required schema column {name!r} is missing.",
                    column=name,
                )
            )
        if missing or added:
            details = []
            if missing:
                details.append(f"missing={missing!r}")
            if added:
                details.append(f"added={added!r}")
            issues.append(
                AttributeValidationIssue(
                    AttributeIssueType.SCHEMA_DRIFT,
                    f"Observed columns differ from the expected schema: {', '.join(details)}.",
                )
            )

        for name, column_schema in expected.items():
            if name not in frame.columns:
                continue
            series = frame[name]
            if not column_schema.nullable:
                null_positions = self._positions(series.isna())
                if null_positions:
                    issues.append(
                        AttributeValidationIssue(
                            AttributeIssueType.NULL_VALUE,
                            f"Column {name!r} contains {len(null_positions)} null value(s).",
                            column=name,
                            row_positions=null_positions,
                        )
                    )

            invalid_positions = self._invalid_type_positions(
                series,
                column_schema.data_type,
            )
            if invalid_positions:
                issues.append(
                    AttributeValidationIssue(
                        AttributeIssueType.INVALID_DATA_TYPE,
                        f"Column {name!r} contains {len(invalid_positions)} value(s) that are "
                        f"not {column_schema.data_type.value}.",
                        column=name,
                        row_positions=invalid_positions,
                    )
                )

        if schema.id_column in frame.columns:
            ids = frame[schema.id_column]
            duplicate_positions = self._positions(ids.notna() & ids.duplicated(keep=False))
            if duplicate_positions:
                issues.append(
                    AttributeValidationIssue(
                        AttributeIssueType.DUPLICATE_ID,
                        f"ID column {schema.id_column!r} contains duplicate values.",
                        column=schema.id_column,
                        row_positions=duplicate_positions,
                    )
                )

        return AttributeValidationResult(len(frame), tuple(issues))

    @classmethod
    def _invalid_type_positions(
        cls,
        series: pd.Series[Any],
        expected_type: AttributeDataType,
    ) -> tuple[int, ...]:
        predicate = cls._predicate(expected_type)
        invalid = series.map(lambda value: not pd.isna(value) and not predicate(value))
        return cls._positions(invalid)

    @staticmethod
    def _predicate(expected_type: AttributeDataType) -> ValuePredicate:
        predicates: dict[AttributeDataType, ValuePredicate] = {
            AttributeDataType.STRING: lambda value: isinstance(value, str),
            AttributeDataType.INTEGER: lambda value: (
                isinstance(value, int) and not isinstance(value, bool)
            ),
            AttributeDataType.FLOAT: lambda value: (
                isinstance(value, (int, float)) and not isinstance(value, bool)
            ),
            AttributeDataType.BOOLEAN: lambda value: isinstance(value, bool),
            AttributeDataType.DATETIME: lambda value: isinstance(value, pd.Timestamp),
        }
        return predicates[expected_type]

    @staticmethod
    def _positions(mask: pd.Series[Any]) -> tuple[int, ...]:
        return tuple(position for position, matched in enumerate(mask) if bool(matched))
