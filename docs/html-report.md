# HTML Quality Report

`HtmlReportRenderer` produces a self-contained HTML report from the
`QualityReport` domain model. The report includes a summary, a quality
score, check/severity statistics, the list of errors, and unique
recommendations.

Install the reporting extra first:

```bash
uv sync --extra report
```

Usage example:

```python
from geoqc.domain.models import GeographicPoint, QualityReport, QualityReportIssue
from geoqc.domain.rules import Severity
from geoqc.infrastructure.reporting import HtmlReportRenderer

report = QualityReport(
    title="Parcel Quality Control",
    dataset_name="parcels.gpkg",
    total_checks=5,
    passed_checks=4,
    issues=(
        QualityReportIssue(
            code="GEO-001",
            title="Self intersection",
            description="Polygon boundary intersects itself.",
            severity=Severity.ERROR,
            category="Geometry",
            recommendation="Repair polygon topology and validate it again.",
            location="Feature 42",
            map_location=GeographicPoint(latitude=-6.1754, longitude=106.8272),
        ),
    ),
)

HtmlReportRenderer().write(report, "reports/quality.html")
```

## Quality score and badge

The quality score starts at `100` and is reduced for each issue based on
its severity:

| Severity | Penalty per issue |
| --- | ---: |
| Info | 1 |
| Warning | 5 |
| Error | 10 |
| Critical | 25 |

The formula is `max(0, 100 - total_issue_penalty)`, so the result always
falls in the 0–100 range. The number of passed checks is shown as a
separate statistic and does not affect the score. A report with no issues
has a score of `100.0`.

The score maps to the following badge, with an inclusive lower bound:

| Score | Badge |
| --- | --- |
| 90–100 | Excellent |
| 75–89 | Good |
| 50–74 | Fair |
| 0–49 | Poor |

The badge is available through the `QualityReport.quality_badge` domain
property and is shown alongside the score in the HTML report. The template
uses Jinja2 auto-escaping, requires no external assets, is responsive on
small screens, and has a dedicated print stylesheet.

## Interactive map

Issues that have a `map_location` are automatically shown on a Folium map
embedded in the HTML report. Coordinates must be WGS84 (`latitude`,
`longitude`). Markers follow the report's severity colors, popups show the
issue detail and recommended action, and the **View on map** button on each
error card will:

1. scroll the user to the map section;
2. animate a zoom to the error's location; and
3. open the associated marker's popup.

If a report has no issues with coordinates, the map section and navigation
button are not rendered. The basemap requires an internet connection when
the report is opened; all issue data and interaction logic remain in the
generated HTML file itself.
