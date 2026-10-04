"""Public conversion from audit results to renderer-ready reports."""

from geoqc.domain.models import DatasetAuditResult
from geoqc.domain.models.quality_report import QualityReport, QualityReportIssue


def build_quality_report(result: DatasetAuditResult) -> QualityReport:
    """Convert a dataset audit into the existing renderer-ready report model."""
    issues = tuple(
        QualityReportIssue(
            code=item.code,
            title=item.title,
            description=item.message,
            severity=item.severity,
            category=item.category.title(),
            recommendation=item.recommendation,
            location=(
                f"{item.layer or result.dataset_name}, feature {item.feature_index}"
                if item.feature_index is not None
                else item.layer or result.dataset_name
            ),
        )
        for item in result.issues
    )
    return QualityReport(
        title="GeoQC dataset quality report",
        dataset_name=result.dataset_name,
        total_checks=max(1, result.feature_count),
        passed_checks=max(
            0,
            result.feature_count
            - len({item.feature_index for item in result.issues if item.feature_index is not None}),
        ),
        issues=issues,
        summary=(
            f"Quality score {result.quality_score:.2f}/100; "
            f"{len(result.issues)} issue(s) found across {result.feature_count} feature(s)."
        ),
    )
