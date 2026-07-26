# Axis Order Detector

The Axis Order Detector checks whether latitude and longitude values may be
swapped in a geographic bounding box. The detector lives in the application
layer and does not depend on any GIS library, filesystem, CLI, or API.

## Input contract

`CoordinateBounds` accepts a raw bounding box in the order:

```text
minimum_x, minimum_y, maximum_x, maximum_y
```

The detector evaluates two interpretations:

1. **Declared:** `x = longitude`, `y = latitude`.
2. **Swapped:** `x = latitude`, `y = longitude`.

Each interpretation must satisfy the geographic range longitude
`[-180, 180]` and latitude `[-90, 90]`. The bounding box must also contain
finite numbers with a positive width and height.

## Spatial validation

The optional `expected` parameter is the `GeographicBounds` area the dataset
is business-expected to fall within — for example, a country's boundary. The
detector tests for **positive overlap area** between the expected bounds and
each interpretation. A bounding box that only touches an edge does not count
as overlapping.

Expected bounds matter most when every value falls within `[-90, 90]`,
because both interpretations can look numerically valid in that case.

## Result status

| Status | Meaning |
|---|---|
| `correct` | Only the longitude/latitude interpretation is valid or spatially matches. |
| `likely_swapped` | Only the latitude/longitude interpretation is valid or spatially matches. |
| `ambiguous` | Both interpretations remain plausible; evidence is insufficient. |
| `invalid` | No interpretation is geographically valid or matches the expected bounds. |

The detector deliberately uses `likely_swapped` rather than absolute
certainty. Automatically correcting coordinates without verifying the CRS
and source metadata can damage data that was actually correct.

## Usage example

```python
from geoqc.application.services import AxisOrderDetector
from geoqc.domain.models import CoordinateBounds, GeographicBounds

detector = AxisOrderDetector()
result = detector.detect(
    CoordinateBounds(-6.3, 106.7, -6.1, 106.9),
    expected=GeographicBounds(95, -11, 141, 6),
)

assert result.status == "likely_swapped"
assert result.swapped_bounds == GeographicBounds(106.7, -6.3, 106.9, -6.1)
```

## Limitations

- Input is assumed to be geographic coordinates in degrees, not projected
  coordinates.
- A bounding box crossing the antimeridian is not yet supported by
  `GeographicBounds`.
- Overlap proves location plausibility, not dataset identity.
- An expected area that is too large can make both interpretations
  `ambiguous`.
- The detector does not read CRS axis metadata; combine it with the CRS
  Consistency Scanner at the orchestration layer for that check.

For an `ambiguous` result, use more specific expected bounds or validate
against a reference feature. For `likely_swapped`, fix the axis mapping at
ingest time and keep the source data as audit evidence.
