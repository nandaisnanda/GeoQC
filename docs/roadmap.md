# Roadmap

Each milestone below required an ADR and acceptance criteria before
implementation. Status reflects the `0.1.0` release.

1. **Foundation** — *done.* Clean Architecture layout, dependency rules,
   tooling, and documentation.
2. **Domain discovery** — *done.* Terminology, input/output contracts, error
   model, and rule contract defined in `domain/`.
3. **First vertical slice** — *done.* Geometry validation ships end to end:
   library API (`validate_geometry`), the `ShapelyGeometryValidator`
   adapter, and full test coverage. CRS consistency, datum-shift,
   axis-order, attribute, batch-processing, and reporting building blocks
   are also implemented as library services (see [docs/index.md](index.md)).
4. **Delivery adapters** — *done.* The CLI exposes CRS scanning, datum-shift
   and axis-order detection, deterministic batch auditing, and atomic HTML
   reports in addition to the canonical `audit` workflow. Commands share
   deterministic output and the `0`/`1`/`2`/`3` exit-code contract documented
   in [docs/cli.md](cli.md).
5. **Web workflow** — *done for the shipped slice.* The `apps/web` React
   client integrates with `POST /api/geometry/validate`, including loading,
   error, empty, responsive, and dark-mode states.
6. **Production hardening** — *done for process-local deployment.* Typed
   settings, production-safe authentication, bounded identity-aware rate
   limiting, request correlation, one structured error contract, structured
   redacted logs, bounded low-cardinality metrics, hardened uploads, and
   bounded asynchronous validation jobs are implemented. Rate counters,
   metrics, and jobs are non-durable and not shared across workers;
   [deployment guidance](api.md#deployment-guidance) documents replacement
   with shared external services.

## Remaining roadmap

- Additional committed geospatial fixtures for uncommon drivers and malformed
  files, extending the generated datasets already covered by
  `tests/integration/`.
- Durable distributed job, rate-limit, and metrics backends for horizontally
  scaled deployments.
