# GeoQC: rules for Claude

## Purpose
GeoQC finds and fixes errors in vector GIS data in one command, with results
that open in QGIS. Focus: Indonesian datasets.

## Code map
- CLI: src/geoqc/interfaces/cli/main.py
- Checks and repairs: src/geoqc/infrastructure/gis/
- Domain models: src/geoqc/domain/models/
- Public API: src/geoqc/__init__.py (do not add exports unless the task says so)
- Sample data: examples/sample_defects.gpkg, testdata/

## Hard rules
- Never git commit, push, or create branches.
- Only edit files needed for the current task. If you need more than 3 source
  files, stop and ask first.
- No new modules, dependencies, public API, or refactors unless the task says so.
- Do not touch: apps/web, src/geoqc/interfaces/api, benchmarks, .github,
  pyproject.toml.
- Do not rename or delete existing functions.
- Do not edit existing tests to make them pass. If one breaks, fix the code or ask.
- No "enterprise" or "intelligence" in new names or messages.

## Working style
- Read only what you need. Use grep to find code; do not read the whole repo.
- Tasks marked PLAN FIRST: show a plan (max 5 bullets) and wait for "ok".
- Test with: uv run pytest <related test files> -q --no-cov
  then: uv run ruff check <changed files>
- Run the full suite only when I say "final check".
- When done, reply in max 5 lines: changed files, tests added, test result.
