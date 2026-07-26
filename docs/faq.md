# Frequently asked questions

## What does GeoQC actually check?

The stable `validate_geometry()` API checks one Shapely geometry for empty or
invalid values, self-intersections, ring errors, and duplicate vertices. The
broader library also provides CRS consistency, datum-shift, and axis-order
checks, an extensible rule engine, batch processing, and optional HTML/
interactive-map reporting. See [docs/index.md](index.md) for the full list.

## Does GeoQC repair or modify my data?

No. GeoQC only reports issues; it never rewrites, repairs, or silently
modifies source datasets or files you pass to it.

## Why are KML and GML rejected by the API?

Both are XML-based formats that can introduce external-entity or
external-resource risks if parsed from untrusted input. The optional HTTP
API only accepts Shapefile, GeoJSON, GeoPackage, and FlatGeobuf uploads. The
Python library itself has no such restriction — see the
[application services](index.md) for direct, in-process use.

## Which parts of the API are considered stable?

Only names exported directly from the `geoqc` package (`from geoqc import
...`) are stable public API during the `0.x` series, per
[README.md](../README.md#documentation). Everything else — including the
`domain`, `application`, and `infrastructure` submodules — is an advanced API
that may change with notice in [CHANGELOG.md](../CHANGELOG.md).

## Can the CLI audit a folder in parallel?

Yes. Run `geoqc audit PATH`; GeoQC discovers supported datasets one level deep
(add `--recursive`/`-r` to descend into subdirectories) and selects a
memory-safe process count. `--workers N` sets an upper bound,
not an unsafe override. Scanner- and detector-specific commands remain tracked
in [the roadmap](roadmap.md). See [docs/cli.md](cli.md) and
[parallel streaming audits](parallel-streaming.md) for the current surface.

## Can I run the API on the public internet?

Not without additional infrastructure. The API has no built-in
authentication, rate limiting, or TLS. See
[Deployment guidance](api.md#deployment-guidance) for what to add at a
reverse proxy before exposing it beyond your own machine.

## How do I report a bug or request a feature?

Open an issue using the bug report or feature request template on
[GitHub Issues](https://github.com/GeoQC/geoqc/issues). For anything
that could be a security vulnerability, follow [SECURITY.md](../SECURITY.md)
instead of filing a public issue.

## How do I contribute?

See [CONTRIBUTING.md](../CONTRIBUTING.md) for local setup, quality
requirements, and the pull request process.
