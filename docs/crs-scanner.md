# CRS Consistency Scanner

The CRS Consistency Scanner audits coordinate reference system metadata across
multiple vector datasets without loading their feature rows.

## Responsibilities

1. Read CRS metadata through an application port.
2. Normalize CRS definitions to canonical WKT2:2019 in the infrastructure adapter.
3. Select the first dataset with a valid CRS as a deterministic baseline.
4. Classify every input while preserving input order.
5. Return an immutable audit result suitable for CLI, API, or report adapters.

## Status model

| Status | Meaning |
| --- | --- |
| `consistent` | The normalized CRS equals the baseline CRS. |
| `mismatch` | The dataset has a valid CRS that differs from the baseline. |
| `missing` | The dataset does not declare CRS metadata. |
| `error` | The dataset cannot be opened or its CRS cannot be parsed. |

`CrsAuditResult.is_consistent` is true only for a non-empty audit where every
dataset is `consistent`. `mismatched_datasets` intentionally excludes missing
and unreadable datasets so consumers can distinguish projection conflicts from
metadata quality problems.

## Python usage

```python
from geoqc.application.services import CrsConsistencyScanner
from geoqc.domain.models import DatasetSource
from geoqc.infrastructure.gis import PyogrioCrsMetadataReader

scanner = CrsConsistencyScanner(PyogrioCrsMetadataReader())
result = scanner.scan(
    [
        DatasetSource("survey.gpkg", layer="parcels"),
        DatasetSource("roads.geojson"),
    ]
)

for dataset in result.mismatched_datasets:
    print(dataset.source.identifier, dataset.crs.display_name if dataset.crs else None)
```

The current vertical slice exposes the Python API only. CLI, FastAPI, and HTML
serialization adapters should consume `CrsAuditResult` in later iterations;
they must not duplicate scanner logic.

## Architecture

```text
domain/models/crs.py
        ^
application/ports/crs_metadata.py
application/services/crs_scanner.py
        ^
infrastructure/gis/pyogrio_crs_reader.py
```

- **Domain** contains framework-free dataset, CRS, and audit value objects.
- **Application** owns comparison policy and depends on a structural reader port.
- **Infrastructure** uses `pyogrio.read_info` for metadata-only access and
  `pyproj.CRS` for parsing and canonicalization.

The scanner compares canonical WKT instead of authority strings because valid
CRS definitions do not always have an EPSG authority. The adapter still exposes
an authority such as `EPSG:4326` when one can be identified.

## Operational notes

- Multi-layer containers should specify `DatasetSource.layer` explicitly.
- The scanner is fail-soft per dataset: one broken source is recorded as an
  `error`, while remaining sources are still audited.
- Dataset access errors are sanitized into the domain-level
  `DatasetMetadataReadError`; raw GDAL/pyogrio exceptions do not cross the port.
- No reprojection is performed. This scanner audits metadata only.