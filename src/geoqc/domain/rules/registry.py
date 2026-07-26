"""Registry used to discover rules without coupling them to the engine."""

from collections.abc import Iterable, Iterator

from geoqc.domain.exceptions import DuplicateRuleError, UnknownRuleError
from geoqc.domain.rules.base import Rule


class RuleRegistry[ContextT]:
    """Insertion-ordered collection of rules with unique identifiers."""

    def __init__(self, rules: Iterable[Rule[ContextT]] = ()) -> None:
        self._rules: dict[str, Rule[ContextT]] = {}
        for rule in rules:
            self.register(rule)

    def register(self, rule: Rule[ContextT]) -> None:
        """Register a rule while preserving deterministic execution order."""
        if not rule.id.strip():
            raise ValueError("Rule id must not be empty")
        if rule.id in self._rules:
            raise DuplicateRuleError(f"Rule {rule.id!r} is already registered")
        self._rules[rule.id] = rule

    def get(self, rule_id: str) -> Rule[ContextT]:
        """Return one rule by identifier."""
        try:
            return self._rules[rule_id]
        except KeyError as error:
            raise UnknownRuleError(f"Rule {rule_id!r} is not registered") from error

    def select(self, rule_ids: Iterable[str] | None = None) -> tuple[Rule[ContextT], ...]:
        """Resolve requested rules, or all rules in registration order."""
        if rule_ids is None:
            return tuple(self._rules.values())
        return tuple(self.get(rule_id) for rule_id in rule_ids)

    def __iter__(self) -> Iterator[Rule[ContextT]]:
        return iter(self._rules.values())

    def __len__(self) -> int:
        return len(self._rules)
