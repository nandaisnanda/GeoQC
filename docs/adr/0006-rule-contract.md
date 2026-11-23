# 0006: Rule contract metadata and finding kinds

Status: Accepted

## Context

Findings carry no record of how they were established, which rule version
produced them, or where a threshold came from. Reports cannot separate a hard
rule violation from a statistical hint or a contextual oddity such as a
dead-end road. Rules also have no version, so a change in logic cannot be
traced in an old report.

## Decision

Add the following to `geoqc.domain.rules`. All of it is pure domain code.

- `FindingKind`: `RULE_VIOLATION` (default), `STATISTICAL_ANOMALY`,
  `AI_SUSPICION`, `CONTEXTUAL_INCONSISTENCY`, `CONFIRMED_ERROR`.
  `RuleFinding` and `AuditIssue` gain a `kind` field defaulting to
  `RULE_VIOLATION`.
- `Tolerance(value, unit)`: finite, non-negative value with a non-empty unit.
- `Provenance(origin, source)`: origin is `built-in`, `preset` or `profile`.
- `RuleMetadata(rule_id, severity, version="1.0.0", tolerance=None,
  provenance=built-in)`: a separate value object. `version` must be semver
  2.0.0.
- `RuleRegistry.register(rule, metadata=None)` stores metadata and rejects an
  id mismatch or an invalid semver. Without metadata it derives defaults from
  the rule. `RuleRegistry.metadata(rule_id)` reads it back.
- `AuditIssue` gains `rule_version` (semver, default `1.0.0`) and `provenance`
  (default built-in).

`FindingKind` is exported from `geoqc.domain.rules` only.

Serialization of `kind`, `rule_version` and `provenance` to JSON, GeoPackage
and HTML is out of scope here and follows in a second change. `to_dict()`
output of `AuditIssue` is unchanged in this change.

Dead-end findings at info level will use `CONTEXTUAL_INCONSISTENCY` in that
second change.

## Alternatives rejected

- **Add `version`, `tolerance` and `provenance` to the `Rule` Protocol.**
  `Rule` is `runtime_checkable`, so `isinstance` checks would fail for every
  existing rule and third-party rule that lacks the new attributes. All
  built-in rules would have to change at once. Rejected for compatibility.
  Metadata lives in `RuleMetadata` with defaults, and the Protocol is
  unchanged.

## Consequences

- Existing rules, registries and `AuditIssue` callers work without edits.
- A rule that needs a non-default version or tolerance supplies a
  `RuleMetadata` at registration.
- The engine does not yet copy metadata into results. Adapters read it from
  the registry.
- `FindingKind` says how a finding was reached. It does not rank certainty.
  `AI_SUSPICION` findings stay suggestions and never trigger automatic repair.
