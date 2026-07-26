# ADR 0003: Automatic Audit Engine Detection

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

GeoPandas is efficient for small datasets but materializes the full dataset. The Streaming Engine has bounded memory behavior and is safer for large or complex datasets, but forcing callers to choose an engine would change the public API and expose infrastructure concerns.

## Decision

Introduce an application-level `EngineDecisionService` and immutable profile/decision models. Infrastructure supplies a bounded `DatasetProfiler` and two execution adapters. The composition root dispatches transparently and returns the pre-existing audit result.

The policy selects Streaming when any configured safety boundary is reached. It considers file size, feature count, estimated memory, available RAM, and sampled vertex complexity. Profiling reads metadata plus at most 256 features.

Engine choices and reasons are logged. They are not added to the public response contract.

## Consequences

- Small datasets retain the simple, fast GeoPandas path.
- Large, complex, or memory-risky datasets use bounded streaming automatically.
- Selection policy is deterministic and unit-testable without GIS libraries.
- Both engines must remain semantically identical; parity tests enforce this.
- Profiling adds one bounded sample read before execution.
- Threshold changes require tests and documentation because they affect operational behavior.
