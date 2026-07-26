# Contributing to GeoQC

Thank you for helping improve GeoQC. Participation is governed by the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Before starting

1. Search existing issues and pull requests.
2. Open an issue before substantial changes so scope and design can be agreed.
3. Do not add features unrelated to the accepted issue.
4. Preserve the dependency rules in [docs/architecture.md](docs/architecture.md).
5. Never include private datasets, credentials, or generated reports.

## Local setup

Install [uv](https://docs.astral.sh/uv/) and Node.js 22 or a current supported
LTS release, then run:

```bash
uv sync --all-extras --all-groups
npm --prefix apps/web ci
```

## Quality requirements

Before submitting a pull request, run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
npm --prefix apps/web run check
```

- Add complete type hints to Python code.
- Add or update tests for every behavior change.
- Keep errors actionable and avoid exposing local paths or internal details.
- Update documentation when contracts, usage, or architecture change.
- Do not change stable behavior without a documented deprecation process.
- Use English for code, comments, commits, issues, and documentation.

## Pull requests

Use Conventional Commits when practical and keep each pull request focused on
one goal. Complete the pull request template, include tests, and explain any
performance or security implications. Maintainers may request smaller commits
or an architecture decision record for cross-layer changes.

## Security reports

Do not disclose suspected vulnerabilities in public issues. Follow the private
reporting process in [SECURITY.md](SECURITY.md).

By submitting a contribution, you agree that it may be distributed under the
project's [MIT License](LICENSE).
