# Changelog

All notable changes to GeoQC are documented here. This project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Modular dataset auditing, profile validation, scoring, exports, and legacy wrappers
  now share a single implementation. The historical API entry point re-exports
  the canonical router-based application.
- Disabled checks consistently report `Check not selected by quality profile.`
  Legacy argument and wrapper deprecations are explicitly tested.

### Added

- Public `geoqc.audit_dataset()` workflow with deterministic dataset metadata,
  geometry/CRS/schema/topology/spatial check results, actionable skipped-check
  reasons, normalized issue details, and automatic streaming engine selection.
- `geoqc audit` now consumes the unified workflow while preserving folder and
  recursive discovery, multiprocessing, benchmarking, and exit codes.

- Phase-2 declarative topology rules for boundary matching, line connectivity,
  overshoot/undershoot, allowed geometry types, multipart restrictions, acute
  angles, minimum segment/vertex distances, touch/intersect/cover predicates,
  attribute-driven overlap policies, and precision-grid validation.

- Unified `audit_file`, `audit_geodataframe`, `audit_layers`, and
  `run_quality_workflow` APIs covering geometry, topology, CRS, and attribute
  checks through one versioned result contract.
- Shareable JSON/YAML quality profiles, stable issue fingerprints with optional
  business feature IDs, weighted explainable scoring, quality gates, repair
  plans with conflict detection, atomic issue GeoPackages, and one-call
  JSON/HTML reports.
- `geoqc check` profile-driven CLI workflow with issue/report outputs and
  conventional pass/fail/error exit codes.

- Public `repair_road_network` API with conservative endpoint snapping, full
  intersection noding, and source-feature provenance.
- Safe `geoqc repair-roads` file workflow with attribute preservation, atomic
  GeoPackage output, CRS/layer/size validation, overwrite protection, and an
  optional JSON report.

### Fixed

- Road analysis now inspects every `MultiLineString` part instead of only the
  longest part and reports unnoded crossings and T-junctions.

## [0.1.0] - 2026-07-26

### Added

- Initial typed geometry-validation API and clean-architecture project layout.
- CRS, datum-shift, axis-order, attribute, rule-engine, batch, and reporting
  building blocks.
- Intelligent topology repair: minimal-change fixes for self-intersections,
  invalid rings, duplicate vertices, and slivers on a single geometry, plus
  cross-feature overlap resolution (deterministic erase policy) and enclosed-gap
  filling on a coverage. Every result keeps before/after WKT, an action audit
  trail, and shape-shift/area metrics; a stateful `RepairSession` adds
  preview, apply, and undo. New public API `repair_geometry`,
  `repair_geometries`, `open_repair_session`, and `RepairConfig`; a bounded HTTP
  preview endpoint preserves attributes/CRS; and the web client adds
  Preview/Apply/Undo plus repaired-GeoJSON/report downloads. Includes unit and
  integration tests and complete topology-repair/API documentation.
- Lazy GeoParquet scans with column projection, Arrow predicate pushdown,
  bounded readahead, and Streaming Engine compatibility.
- Atomic bounded-memory GeoParquet writer with GeoParquet 1.1 metadata,
  compression/row-group tuning, tests, cross-format benchmark, and usage guide.
- Optional low-overhead, process-local audit benchmarking for runtime, CPU,
  memory, feature/geometry/rule counts, selected engine, chunk size, and worker
  count.
- Self-contained HTML and JSON benchmark reports plus Markdown reports with a
  Mermaid chart.
- CLI benchmark controls, modular no-op recorder, tests, overhead harness, and
  complete benchmark documentation.

- Automatic, resource-aware selection between GeoPandas and the Streaming Engine, with bounded profiling, decision logging, and cross-engine parity tests.
- Memory-aware dataset-level parallel streaming with deterministic aggregation,
  isolated failures, CLI folder audits, progress events, and `1`/`2`/`4`/`8`
  worker benchmark tooling.

- Modular, Arrow-based Streaming Engine with independent readers, iterator,
  processors, and bounded result collectors.
- Chunked GeoPackage, Shapefile, GeoJSON, and GeoParquet support plus parity,
  integration, error-path tests, and a manual memory benchmark.
- `SECURITY.md`, `CODE_OF_CONDUCT.md`, and `CITATION.cff`.
- GitHub issue forms (bug report, feature request), pull request template,
  CI workflow (lint, type check, test, dependency audit across the Python
  matrix and the web client), a PyPI trusted-publishing release workflow,
  and Dependabot configuration for `uv`, `npm`, and GitHub Actions.
- `docs/cli.md`, `docs/api.md`, `docs/faq.md`, and `docs/release-checklist.md`,
  closing every documentation link previously referenced from `README.md`
  and `CONTRIBUTING.md`.
- CI/PyPI/license badges in `README.md`.
- `GEOQC_ENVIRONMENT=production` now disables `/docs`, `/redoc`, and
  `/openapi.json` on the optional API; `GEOQC_LOG_LEVEL` now configures
  logging at API startup. Both were previously documented in `.env.example`
  but unused.
- `apps/web` `npm run check` script (lint + build + test), matching the
  command already referenced by `CONTRIBUTING.md` and `README.md`.

### Changed

- Translated `docs/index.md`, `docs/architecture.md`, `docs/development.md`,
  `docs/roadmap.md`, `docs/datum-shift-detector.md`,
  `docs/axis-order-detector.md`, `docs/batch-processing.md`,
  `docs/html-report.md`, and `docs/adr/*` from Indonesian to English, and
  updated `docs/index.md` / `docs/roadmap.md` to reflect the features
  actually shipped in `0.1.0` instead of a pre-implementation state.
- The FastAPI app now reports `geoqc.__version__` instead of a hardcoded
  literal, so the version is defined in one place
  (`src/geoqc/__init__.py`) and read everywhere else.
- Removed the redundant `License :: OSI Approved :: MIT License` classifier
  from `pyproject.toml` now that the SPDX `license = "MIT"` expression is
  used.

### Removed

- Empty, unused stub files that were shipping as 0-byte modules in the
  built wheel: `src/geoqc/infrastructure/reporting/export.py` and
  `src/geoqc/interfaces/cli/workflow.py`, along with their empty test and
  documentation placeholders.

### Security

- Restricted archive members, upload formats, request sizes, dataset
  complexity, and client-visible exception details.
- The optional API's interactive documentation can now be disabled in
  production via `GEOQC_ENVIRONMENT=production`.

[Unreleased]: https://github.com/nandaisnanda/GeoQC/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nandaisnanda/GeoQC/releases/tag/v0.1.0
