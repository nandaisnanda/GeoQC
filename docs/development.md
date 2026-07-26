# Developer guide

## Toolchain

- Python 3.12+ (development is pinned to 3.13 via `.python-version`)
- `uv` for the environment, dependency resolution, and lockfile
- Ruff for formatting/linting
- mypy in strict mode for static typing
- Pytest and coverage for testing
- Node.js 22+ for the React frontend

## Local setup

```bash
uv sync --all-extras --all-groups
npm --prefix apps/web ci
```

## Quality gate

```bash
uv sync --all-extras --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
npm --prefix apps/web run check
```

Every feature must have a unit test and a documentation update. Add new
dependencies only to the layer that needs them. Never import GeoPandas or any
other dataframe-oriented GIS/web framework from `domain` — see
[architecture.md](architecture.md) for the enforced dependency rule (checked
by `tests/architecture/test_dependencies.py`).

For large-dataset audit development, read the
[Streaming Engine guide](streaming-engine.md). Keep processors stateless across
chunks and collectors bounded; never accumulate raw chunks or complete feature
tables. Run `uv run pytest tests/integration/test_streaming_formats.py` after
changing a reader and use `benchmarks/streaming_geometry.py` for representative
memory/performance comparisons.

For multi-dataset concurrency, read
[parallel streaming audits](parallel-streaming.md). Run the benchmark with
requested worker counts `1`, `2`, `4`, and `8`:

```bash
uv run python benchmarks/parallel_streaming.py --datasets 8 --features 100000
```

The scheduler can report fewer effective workers when CPU or current available
memory makes the requested level unsafe. Benchmark output is diagnostic and is
not a CI pass/fail threshold.

## Definition of done

- Scope matches the issue; no speculative features are added.
- Every function, method, parameter, and return value has type hints.
- Unit tests cover the happy path, failure paths, and relevant edge cases.
- Documentation and the changelog are updated.
- The quality gate passes.
- Stable public API is never removed; breaking changes go through a
  documented deprecation process.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the pull request process and
[docs/release-checklist.md](release-checklist.md) for cutting a release.
