"""Rule contract: finding kind, tolerance, provenance, metadata, semver."""

import pytest

from geoqc.domain.exceptions import DuplicateRuleError
from geoqc.domain.models import AuditIssue
from geoqc.domain.rules import (
    FindingKind,
    Provenance,
    ProvenanceOrigin,
    Rule,
    RuleFinding,
    RuleMetadata,
    RuleRegistry,
    Severity,
    Tolerance,
)
from geoqc.domain.rules.examples.non_empty import NonEmptyRule


def test_finding_kind_values_are_stable() -> None:
    assert [kind.value for kind in FindingKind] == [
        "rule_violation",
        "statistical_anomaly",
        "ai_suspicion",
        "contextual_inconsistency",
        "confirmed_error",
    ]


def test_finding_defaults_to_rule_violation() -> None:
    assert RuleFinding(message="Bad.").kind is FindingKind.RULE_VIOLATION


def test_finding_accepts_explicit_kind() -> None:
    finding = RuleFinding(message="Odd.", kind=FindingKind.CONTEXTUAL_INCONSISTENCY)
    assert finding.kind is FindingKind.CONTEXTUAL_INCONSISTENCY


def test_metadata_defaults() -> None:
    metadata = RuleMetadata(rule_id="r.one", severity=Severity.WARNING)
    assert metadata.version == "1.0.0"
    assert metadata.tolerance is None
    assert metadata.provenance == Provenance(ProvenanceOrigin.BUILT_IN, "geoqc")


def test_metadata_keeps_tolerance_and_provenance() -> None:
    metadata = RuleMetadata(
        rule_id="r.one",
        severity=Severity.ERROR,
        version="2.1.0-rc.1+build.5",
        tolerance=Tolerance(0.5, "m"),
        provenance=Provenance(ProvenanceOrigin.PROFILE, "bpn-profile.yaml"),
    )
    assert metadata.tolerance == Tolerance(0.5, "m")
    assert metadata.provenance.origin.value == "profile"


@pytest.mark.parametrize("version", ["1", "1.0", "v1.0.0", "01.0.0", "1.0.0.0", "", "1.0.x"])
def test_metadata_rejects_invalid_semver(version: str) -> None:
    with pytest.raises(ValueError, match="semver"):
        RuleMetadata(rule_id="r.one", severity=Severity.INFO, version=version)


def test_metadata_rejects_blank_rule_id() -> None:
    with pytest.raises(ValueError, match="rule_id"):
        RuleMetadata(rule_id=" ", severity=Severity.INFO)


@pytest.mark.parametrize(
    ("value", "unit"),
    [(-1.0, "m"), (float("nan"), "m"), (float("inf"), "m"), (1.0, " ")],
)
def test_tolerance_rejects_invalid_input(value: float, unit: str) -> None:
    with pytest.raises(ValueError, match="Tolerance"):
        Tolerance(value, unit)


def test_tolerance_allows_zero() -> None:
    assert Tolerance(0.0, "m").value == 0.0


def test_provenance_rejects_blank_source() -> None:
    with pytest.raises(ValueError, match="source"):
        Provenance(ProvenanceOrigin.PRESET, "  ")


def test_registry_assigns_default_metadata_to_existing_rules() -> None:
    registry: RuleRegistry[list[int]] = RuleRegistry([NonEmptyRule()])
    metadata = registry.metadata("core.completeness.non-empty")
    assert metadata.version == "1.0.0"
    assert metadata.severity is Severity.ERROR


def test_registry_stores_explicit_metadata() -> None:
    registry: RuleRegistry[list[int]] = RuleRegistry()
    custom = RuleMetadata(
        rule_id="core.completeness.non-empty",
        severity=Severity.WARNING,
        version="1.2.3",
    )
    registry.register(NonEmptyRule(), custom)
    assert registry.metadata("core.completeness.non-empty") is custom


def test_registry_rejects_metadata_for_another_rule() -> None:
    registry: RuleRegistry[list[int]] = RuleRegistry()
    other = RuleMetadata(rule_id="other.rule", severity=Severity.INFO)
    with pytest.raises(ValueError, match="does not match"):
        registry.register(NonEmptyRule(), other)
    assert len(registry) == 0


def test_registry_rejects_semver_that_bypasses_metadata_validation() -> None:
    registry: RuleRegistry[list[int]] = RuleRegistry()
    metadata = RuleMetadata(rule_id="core.completeness.non-empty", severity=Severity.ERROR)
    object.__setattr__(metadata, "version", "not-semver")
    with pytest.raises(ValueError, match="semver"):
        registry.register(NonEmptyRule(), metadata)
    assert len(registry) == 0


def test_duplicate_registration_still_fails() -> None:
    registry: RuleRegistry[list[int]] = RuleRegistry([NonEmptyRule()])
    with pytest.raises(DuplicateRuleError):
        registry.register(NonEmptyRule())


def test_registry_metadata_for_unknown_rule_fails() -> None:
    from geoqc.domain.exceptions import UnknownRuleError

    with pytest.raises(UnknownRuleError):
        RuleRegistry[list[int]]().metadata("missing")


def test_rule_protocol_is_unchanged_for_rules_without_metadata() -> None:
    assert isinstance(NonEmptyRule(), Rule)


def test_audit_issue_defaults_keep_legacy_output() -> None:
    with pytest.warns(DeprecationWarning):
        issue = AuditIssue("GEO-X", "Bad.", Severity.ERROR, "Fix.", (1,))
    assert issue.kind is FindingKind.RULE_VIOLATION
    assert issue.rule_version == "1.0.0"
    assert issue.provenance.origin is ProvenanceOrigin.BUILT_IN
    assert issue.to_dict() == {
        "code": "GEO-X",
        "message": "Bad.",
        "severity": "error",
        "recommendation": "Fix.",
        "feature_indices": [1],
    }


def test_audit_issue_accepts_new_fields_and_rejects_bad_version() -> None:
    with pytest.warns(DeprecationWarning):
        issue = AuditIssue(
            "GEO-X",
            "Bad.",
            Severity.INFO,
            "Fix.",
            kind=FindingKind.AI_SUSPICION,
            rule_version="1.4.0",
        )
    assert issue.kind is FindingKind.AI_SUSPICION
    with pytest.warns(DeprecationWarning), pytest.raises(ValueError, match="semver"):
        AuditIssue("GEO-X", "Bad.", Severity.INFO, "Fix.", rule_version="1.4")
