# Rule Engine

The GeoQC rule engine uses dependency inversion and structural typing. The engine knows only the
`Rule[ContextT]` protocol; it does not import individual rules or GIS frameworks.

## Contracts

Each rule declares `id`, `name`, `description`, `severity`, `category`, and `execute(context)`. An
execution returns an immutable `RuleResult` containing zero or more `RuleFinding` values.

Contexts are generic. A rule may accept a `GeoDataFrame`, a layer bundle, or a lightweight domain
context while the same engine remains unchanged. Rule sets should use a common compatible context.

## Adding a rule

1. Add one module under an appropriate rules package; keep one concrete rule per file.
2. Implement the `Rule` protocol—inheritance is not required.
3. Test the rule independently.
4. Register it in the application composition root or inject it as a plugin.

```python
registry = RuleRegistry([MyRule(), AnotherRule()])
engine = RuleEngine(registry)
result = engine.execute(context)
```

No modification to `RuleEngine` is required. Registration is explicit by default, which keeps
startup deterministic and avoids import-time side effects. Packaging entry points can be added as
an infrastructure-level plugin discovery adapter when third-party rules are introduced.

## Failure semantics

- `PASSED`: no finding.
- `FAILED`: the rule executed successfully and found quality issues.
- `ERROR`: execution failed operationally.
- `ErrorPolicy.CONTINUE` isolates an exception as an error result.
- `ErrorPolicy.RAISE` wraps it in `RuleExecutionError` for fail-fast workflows.