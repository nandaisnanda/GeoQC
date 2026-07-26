# Security Policy

## Supported versions

GeoQC is currently in the `0.x` (alpha) series. Only the latest published
release on PyPI receives security fixes.

| Version | Supported |
| ------- | --------- |
| 0.x     | Yes       |

## Reporting a vulnerability

Do not open a public GitHub issue for a suspected security vulnerability.

Report it privately using [GitHub's private vulnerability reporting](https://github.com/GeoQC/geoqc/security/advisories/new)
(Security tab -> Report a vulnerability) on the [GeoQC repository](https://github.com/GeoQC/geoqc).
This opens a private advisory visible only to the maintainers until a fix is
ready.

If you cannot use GitHub's private reporting for any reason, open a regular
issue asking a maintainer to open a private channel, without including
vulnerability details.

Please include, where applicable:

- The affected version and installation method (PyPI package, source
  checkout, `apps/web` frontend).
- Steps to reproduce, including a minimal dataset or request payload if the
  issue involves the geometry-validation API or CLI.
- The potential impact (for example: path traversal, denial of service,
  information disclosure).

## Response process

- We aim to acknowledge new reports within 5 business days.
- We aim to provide an initial assessment (confirmed, not applicable, or
  needs more information) within 10 business days.
- Confirmed vulnerabilities are fixed on a private branch, released as a new
  `0.x` version, and disclosed via a GitHub Security Advisory and
  [CHANGELOG.md](CHANGELOG.md) after the fix is available. We credit
  reporters who wish to be credited.

## Scope

In scope:

- The `geoqc` Python package (`src/geoqc`), including the geometry-validation
  API, CLI, and optional FastAPI service.
- The `apps/web` reference frontend, as shipped in this repository.

Out of scope:

- Vulnerabilities in third-party dependencies (GDAL/OGR, GeoPandas, Shapely,
  FastAPI, etc.) — please report those upstream. If a dependency
  vulnerability is directly exploitable through GeoQC's own code paths, we
  still want to hear about it here.
- Denial of service against a deployment that ignores the deployment
  guidance in [README.md](README.md) (running the API on a public interface
  without a reverse proxy, authentication, or rate limiting).
