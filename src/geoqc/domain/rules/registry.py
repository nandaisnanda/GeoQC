"""Registry used to discover rules without coupling them to the engine."""

from collections.abc import Iterable, Iterator

from geoqc.domain.exceptions import DuplicateRuleError, UnknownRuleError
from geoqc.domain.rules.base import Rule
from geoqc.domain.rules.models import RuleMetadata, is_semver


class RuleRegistry[ContextT]:
    """Insertion-ordered collection of rules with unique identifiers."""

    def __init__(self, rules: Iterable[Rule[ContextT]] = ()) -> None:
        self._rules: dict[str, Rule[ContextT]] = {}
        self._metadata: dict[str, RuleMetadata] = {}
        for rule in rules:
            self.register(rule)

    def register(self, rule: Rule[ContextT], metadata: RuleMetadata | None = None) -> None:
        """Register a rule while preserving deterministic execution order.

        Without ``metadata`` the rule gets version 1.0.0, its own severity and
        built-in provenance, so existing callers keep working unchanged.
        """
        if not rule.id.strip():
            raise ValueError("Rule id must not be empty")
        if rule.id in self._rules:
            raise DuplicateRuleError(f"Rule {rule.id!r} is already registered")
        if metadata is None:
            metadata = RuleMetadata(rule_id=rule.id, severity=rule.severity)
        elif metadata.rule_id != rule.id:
            raise ValueError(
                f"Metadata rule_id {metadata.rule_id!r} does not match rule id {rule.id!r}"
            )
        if not is_semver(metadata.version):
            raise ValueError(f"Rule version {metadata.version!r} is not a valid semver string")
        self._rules[rule.id] = rule
        self._metadata[rule.id] = metadata

    def metadata(self, rule_id: str) -> RuleMetadata:
        """Return the metadata registered for one rule."""
        self.get(rule_id)
        return self._metadata[rule_id]

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
