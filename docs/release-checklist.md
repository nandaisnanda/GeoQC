# Release checklist

Steps for cutting a new GeoQC release. GeoQC follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html); only names
exported from the top-level `geoqc` package are covered by its stability
guarantees during the `0.x` series (see [README.md](../README.md#documentation)).

## 1. Prepare

- [ ] Ensure `main` is green: CI (Python matrix + web client) passing.
- [ ] Update [CHANGELOG.md](../CHANGELOG.md): move the `[Unreleased]`
      entries under a new `## [X.Y.Z] - YYYY-MM-DD` heading, and add fresh
      compare/release links at the bottom of the file.
- [ ] Bump the version in **both** places (kept in sync intentionally, not
      auto-generated):
  - `pyproject.toml` → `[project] version`
  - `src/geoqc/__init__.py` → `__version__`
  - `src/geoqc/interfaces/api/main.py` reads `__version__` from the package,
    so it does not need a separate edit.
- [ ] Update `tests/unit/interfaces/test_api.py::test_*` and
      `tests/unit/interfaces/test_cli.py::test_cli_shows_version` if they
      assert a literal version string.

## 2. Verify

```bash
uv sync --all-extras --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
npm --prefix apps/web ci
npm --prefix apps/web run check
uv build
```

- [ ] All commands above succeed locally.
- [ ] `uv build` produces a wheel and sdist in `dist/` with the expected
      version in the filename.
- [ ] Inspect the built wheel contents (`python -m zipfile -l dist/geoqc-*.whl`)
      to confirm no unintended files (caches, empty stubs, local data) are
      included.

## 3. Tag and release

- [ ] Commit the version bump and changelog update.
- [ ] Tag the commit: `git tag vX.Y.Z && git push origin vX.Y.Z`.
- [ ] Create a GitHub Release from the tag, using the corresponding
      CHANGELOG section as the release notes.
- [ ] Publishing a GitHub Release triggers `.github/workflows/publish.yml`,
      which builds and uploads the package to PyPI via
      [trusted publishing](https://docs.pypi.org/trusted-publishers/) (no
      stored API token). Confirm the `geoqc` project on PyPI has this
      repository's `publish.yml` workflow registered as a trusted publisher
      before the first automated release.

## 4. After release

- [ ] Confirm `python -m pip install geoqc==X.Y.Z` installs successfully
      from PyPI in a clean environment.
- [ ] Confirm the GitHub Release and PyPI project page both show the correct
      version and changelog.
- [ ] Open a new `[Unreleased]` section at the top of
      [CHANGELOG.md](../CHANGELOG.md) for the next cycle.
