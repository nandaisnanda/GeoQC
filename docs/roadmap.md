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
4. **Delivery adapters** — *in progress.* The HTTP contract is stable for
   `POST /api/geometry/validate` (see [docs/api.md](api.md)). The CLI exposes
   the dataset-level `audit` workflow (see [docs/cli.md](cli.md));
   wiring the scanner/detector/batch services to CLI subcommands is not yet
   done.
5. **Web workflow** — *done for the shipped slice.* The `apps/web` React
   client integrates with `POST /api/geometry/validate`, including loading,
   error, empty, responsive, and dark-mode states.
6. **Production hardening** — *in progress.* Done: request/response
   validation, upload size and feature-count limits, filename and
   extension/driver validation, structured CI (lint, type check, test,
   dependency audit) and Dependabot. Not yet done: authentication, rate
   limiting, observability (structured logs, metrics, correlation IDs), and
   asynchronous job execution for large datasets — see
   [Deployment guidance](api.md#deployment-guidance) for the current
   mitigation (place these at a reverse proxy).

## Not yet started

- CLI subcommands for CRS scanning, datum-shift detection, axis-order
  detection, batch processing, and HTML report generation.
- Additional committed geospatial fixtures for uncommon drivers and malformed
  files, extending the generated datasets already covered by
  `tests/integration/`.
- Authentication, rate limiting, and observability for the optional API.
