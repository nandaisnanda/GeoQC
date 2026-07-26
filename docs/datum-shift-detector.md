# Datum Shift Detector

`DatumShiftDetector` checks for an abnormally large horizontal shift between
two datums over an area of interest (AOI). The implementation uses
PyProj/PROJ, but the domain and application layer contracts do not depend on
any GIS library.

## Why is an AOI required?

Datum operations are local. The best-available operation, correction grid,
accuracy, and shift magnitude can all change with location. For that reason
the detector never draws a global conclusion from two EPSG codes alone.

The AOI uses longitude/latitude in degrees, ordered:

```text
west, south, east, north
```

An AOI that crosses the antimeridian is not yet supported; split it into two
audits instead.

## Example

```python
from geoqc.application.services import DatumShiftDetector
from geoqc.domain.models import GeographicBounds
from geoqc.infrastructure.gis import PyprojDatumTransformationInspector

detector = DatumShiftDetector(PyprojDatumTransformationInspector())
result = detector.detect(
    "EPSG:4267",  # NAD27
    "EPSG:4326",  # WGS 84
    GeographicBounds(-125, 25, -66, 49),
    threshold_m=5.0,
    grid_size=5,  # 25 sample points
)

print(result.status)  # normal | abnormal | indeterminate
print(result.quality)  # reliable | warning
print(result.summary)
for warning in result.warnings:
    print(f"- {warning}")
print(result.recommendation)
```

## How it works

1. Source and target CRSs are reduced to their geodetic components, so a
   unit/projection change (for example WGS 84 to Web Mercator) is not
   mistaken for a datum shift.
2. `TransformerGroup` selects the best local operation for the AOI.
3. The AOI is sampled as a regular `grid_size × grid_size` grid (default
   3 × 3).
4. Every point is transformed with `always_xy=True` and `errcheck=True`.
5. The distance from each source point to its transformed point is computed
   geodesically on the target ellipsoid.
6. The maximum shift is compared against `threshold_m` (default 5 meters).

The detector never reads dataset features. The caller must supply the
correct CRSs and AOI — for example, from dataset metadata and an extent
already normalized to longitude/latitude.

## Reading the result

### `status`

| Status | Meaning |
|---|---|
| `normal` | Every sampled displacement is at or below the threshold. |
| `abnormal` | At least one sample exceeds the threshold. |
| `indeterminate` | No valid samples are available to draw a conclusion. |

A value exactly equal to the threshold counts as `normal`. `abnormal_samples`
provides the points that exceeded the threshold for detailed reporting.

### `quality`

`quality` is deliberately separate from `status`. A small shift can come
from an operation that should not be trusted, while a large shift can be a
technically valid datum transformation that still needs business
verification.

`warning` is set when:

- the best operation is unavailable;
- PyProj falls back to a ballpark operation;
- the best operation's grid is unavailable;
- the declared accuracy is unknown; or
- the declared accuracy is worse than the audit threshold.

A `normal` result with `warning` set **must not** be treated as
production-ready until the warning is resolved. Missing grid names are
available in `evidence.missing_grids`.

## Choosing a threshold and grid

- `5 m` is an operational default, not a universal standard.
- Choose the threshold from the project's accuracy specification, data
  scale, and the authoritative datum definitions.
- Use a denser grid for large AOIs or regions with high local distortion.
- `grid_size` is bounded to 2–25 to prevent uncontrolled synchronous audits.
- Grid sampling is not continuous proof for every point in the AOI.

## Scientific limitations

- The detector assesses 2D horizontal shift only, not vertical datum or
  epoch/time-dependent transformations.
- Sample coordinates are treated as longitude/latitude in the source datum
  and compared against the result in the target datum. This is a diagnostic
  displacement, not an absolute error against ground truth.
- Grid availability depends on the local PROJ installation and
  network/grid policy.
- Do not correct findings with a manual offset. Verify the source CRS,
  target datum, epoch, and official operation with a geospatial authority.

## Architecture boundary

```text
domain/models/datum_shift.py
        ↑
application/ports/datum_transformation.py
        ↑
application/services/datum_shift_detector.py
        ↑
infrastructure/gis/pyproj_datum_inspector.py
```

The CLI, FastAPI, and HTML report can all consume `DatumShiftAuditResult`
without duplicating classification logic or depending directly on PyProj.
