# ADR 0001: Clean Architecture in a monorepo

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

GeoQC needs a single domain engine shared by the Python library, CLI, API,
report renderer, and web client, while keeping the geospatial and delivery
frameworks free to change independently.

## Decision

Use a monorepo with Clean Architecture. Python uses a `src` layout with
dependencies pointing toward the domain. React remains a separate
application that depends only on the HTTP contract.

## Consequences

- The domain can be tested without any framework and is reused by every
  interface.
- Adapters require explicit mapping and a composition root.
- Boundaries must be maintained through review and, eventually, an
  architecture test (implemented as `tests/architecture/test_dependencies.py`).
- The monorepo simplifies cross-cutting contract changes between the
  backend and frontend, but CI will need path filtering as the project
  grows.
