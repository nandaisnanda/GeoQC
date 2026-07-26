"""Tests for rule registration and lookup."""

import pytest

from geoqc.domain.exceptions import DuplicateRuleError, UnknownRuleError
from geoqc.domain.rules import RuleRegistry
from geoqc.domain.rules.examples import NonEmptyRule


def test_registry_preserves_registration_order_and_selects_rules() -> None:
    first = NonEmptyRule()
    second = NonEmptyRule()
    second.id = "another-rule"
    registry = RuleRegistry[list[object]]([first, second])

    assert tuple(rule.id for rule in registry) == (first.id, second.id)
    assert registry.select([second.id]) == (second,)
    assert len(registry) == 2


def test_registry_rejects_duplicate_ids() -> None:
    with pytest.raises(DuplicateRuleError):
        RuleRegistry[list[object]]([NonEmptyRule(), NonEmptyRule()])


def test_registry_rejects_unknown_id() -> None:
    registry = RuleRegistry[list[object]]()

    with pytest.raises(UnknownRuleError):
        registry.get("missing")
