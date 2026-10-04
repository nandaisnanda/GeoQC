# 0005: One canonical dataset audit result

Status: Accepted

## Decision

`geoqc.audit_dataset()` is the canonical file-based entry point and
`DatasetAuditResult` is the only dataset audit result class. Python and CLI
adapters call the same profile-driven application workflow. The result owns
deterministic JSON, HTML, and findings export methods; renderers and filesystem
details remain adapters.

`audit_file()`, `run_quality_workflow()`, `geoqc check`, and the P0
`DatasetAuditReport` constructor remain temporary deprecated adapters. They
delegate to, or construct, `DatasetAuditResult` and must not contain independent
scoring or reporting logic. `audit_geometries()` remains the lower-level
in-memory geometry API, not a competing file audit.

## Consequences

- New integrations depend on one versioned contract (`schema_version: "1.0"`).
- Output files are atomic and require explicit overwrite permission.
- Legacy callers receive `DeprecationWarning` with a migration target.
- Scoring is advisory and explainable; it is not an official quality standard.

