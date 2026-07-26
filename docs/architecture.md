# GeoQC architecture

## Context and requirements

GeoQC provides the same GIS QC engine to Python, terminal, HTTP, and web
consumers. Geospatial input can be large, untrusted, use different CRSs, and
come from a variety of formats and drivers. The architecture keeps QC rules
deterministic and independent of any delivery framework.

### Quality attributes

1. **Correctness:** CRS, geometry, precision, and nullability must be
   explicit.
2. **Modularity:** a new rule must not change unrelated interfaces or
   adapters.
3. **Testability:** the domain and use cases must be testable without files,
   network access, or a web server.
4. **Scalability:** use cases do not assume execution only within an HTTP
   process; a job worker can be added later.
5. **Security:** file uploads, paths, data size, and drivers must be
   validated at the boundary.
6. **Observability:** correlation IDs, structured logs, metrics, and timing
   are applied at the adapter layer.
7. **Compatibility:** the public API follows semantic versioning and a
   deprecation policy.

## Clean Architecture

```text
React Web ──HTTP──> FastAPI interface ─┐
Typer CLI ─────────────────────────────┼─> Application use cases ─> Domain
Python public API ─────────────────────┘             │
                                                    v
                           Outbound ports <── Infrastructure adapters
                           (GIS I/O, report, future persistence/jobs)
```

### Dependency rule

- `domain` uses only the Python standard library and never imports a
  GIS/web framework.
- `application` depends only on `domain` and its own port contracts.
- `infrastructure` implements those ports; this is where GeoPandas, Shapely,
  PyProj, Pyogrio, Pandas, NumPy, Jinja2, and Folium are used.
- `interfaces` translates CLI or HTTP input/output and calls the
  application layer.
- `apps/web` communicates only through the HTTP contract; it has no
  knowledge of Python internals.
- The composition root assembles dependencies. The domain never performs
  its own dependency injection.

The core GIS package is the primary dependency. Delivery frameworks are
isolated behind the optional `api` and `report` extras, so library consumers
do not install a stack they do not use.

## Structure

```text
GeoQC/
├── apps/web/                       # React + TypeScript application
├── docs/                           # Architecture and contributor docs
├── src/geoqc/
│   ├── domain/                     # Entities, value objects, QC policies
│   ├── application/                # Use cases and ports
│   ├── infrastructure/
│   │   ├── gis/                    # Geospatial library adapters
│   │   └── reporting/              # HTML/Jinja2/Folium adapters
│   └── interfaces/
│       ├── api/                    # FastAPI delivery adapter
│       └── cli/                    # Typer delivery adapter
└── tests/
    ├── unit/                       # Mirrors architecture layers
    ├── integration/                # Adapter and boundary integration
    └── fixtures/                   # Small, licensed geospatial fixtures
```

## Domain boundaries

The following are candidate bounded contexts describing the shape of the
domain, not a one-to-one map of shipped features:

- **Dataset inspection:** metadata, schema, CRS, and geometry profile.
- **QC rules:** rule definitions, severity, parameters, and evaluation.
- **QC execution:** orchestration, progress, cancellation, and result
  aggregation.
- **Reporting:** rendering results to HTML/map without evaluation logic.

New concrete models are introduced together with their first use case so the
design does not get ahead of real requirements.

## Testing strategy

- Domain unit tests: pure, fast, no GIS I/O.
- Application unit tests: ports replaced with fake/in-memory
  implementations.
- Integration tests: GIS drivers, report templates, the API, and the CLI
  boundary.
- Contract tests: OpenAPI and the web client, as endpoints stabilize.
- Geospatial fixtures must be minimal, redistributable, and carry clear
  provenance.

`tests/integration/` and `tests/fixtures/` currently hold no test modules or
fixtures yet — the layers above are exercised through the unit test suite
today; integration coverage is tracked in [the roadmap](roadmap.md).

## Production evolution

FastAPI does not run heavy work in a blocking manner. Once an asynchronous
job requirement is confirmed, a worker and durable queue will be added
through an application port. Storage, authentication, deployment, and
observability are likewise decided through separate ADRs rather than assumed
in the scaffold.
