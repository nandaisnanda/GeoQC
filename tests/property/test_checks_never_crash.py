"""Property tests: no registered check may crash on dirty geometry.

Each test feeds generated dirty input to one registered check and asserts that it
returns a well-formed result model instead of raising.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace

import geopandas as gpd  # type: ignore[import-untyped]
import pyarrow as pa  # type: ignore[import-untyped]
import pytest
import shapely
from hypothesis import example, given
from hypothesis import strategies as st
from shapely import from_wkt
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from geoqc.application.streaming.geometry import GeometryChunkResult
from geoqc.application.streaming.models import DatasetMetadata, FeatureChunk
from geoqc.domain.models import (
    AttributeOverlapPolicy,
    AttributeRule,
    AttributeRuleType,
    AuditCheckResult,
    CheckStatus,
    DatasetAuditResult,
    DatasetIssue,
    DatasetLayer,
    QualityPreset,
    QualityProfile,
    TopologyRule,
    TopologyRuleType,
)
from geoqc.domain.models.geometry_validation import GeometryValidationResult
from geoqc.domain.rules import ErrorPolicy, ResultStatus, RuleEngine, RuleRegistry
from geoqc.domain.rules.examples import NonEmptyRule
from geoqc.infrastructure.gis.dataset_audit import audit_geodataframe
from geoqc.infrastructure.gis.dataset_checks import _checks_for_result
from geoqc.infrastructure.gis.quality_workflow import audit_geometries, evaluate_topology_rules
from geoqc.infrastructure.gis.shapely_geometry_validator import ShapelyGeometryValidator
from geoqc.infrastructure.gis.streaming.geometry_processor import GeometryChunkProcessor
from tests.property.strategies import (
    attribute_values,
    dirty_geometries,
    dirty_layers,
    dirty_wkb_cells,
)

# NaN coordinates are part of the input space; GEOS warns about them on every call.
pytestmark = pytest.mark.filterwarnings("ignore:invalid value encountered:RuntimeWarning")

CHECK_NAMES = ("geometry", "crs", "attributes", "topology", "spatial")
NEEDS_REFERENCE = frozenset(
    {
        TopologyRuleType.MUST_BE_INSIDE,
        TopologyRuleType.MUST_NOT_INTERSECT,
        TopologyRuleType.BOUNDARY_MUST_MATCH,
        TopologyRuleType.MUST_TOUCH,
        TopologyRuleType.MUST_INTERSECT,
        TopologyRuleType.MUST_COVER,
    }
)
GEOMETRY_TYPES = (
    "Point",
    "LineString",
    "Polygon",
    "MultiPoint",
    "MultiLineString",
    "MultiPolygon",
    "GeometryCollection",
)
CRS_CHOICES = (None, "EPSG:4326", "EPSG:3857", "EPSG:32748")

# Minimal inputs from crashes found by this suite. Each crashed at least one check.
NAN_POLYGON = "POLYGON ((0 0, 0 1, 0 NaN, 0 0))"
ALL_NAN_LINE = "LINESTRING (NaN NaN, NaN NaN)"
BOWTIE = "POLYGON ((0 0, 2 2, 2 0, 0 2, 0 0))"
OVERFLOW_POLYGON = "POLYGON ((0 0, 0 0, 0 1.7976931348623157e308, 0 1.7976931348623157e308, 0 0))"

thresholds = st.one_of(
    st.sampled_from((0.0, 1e-12, 0.5, 1.0, 1e9)),
    st.floats(min_value=0, max_value=10, allow_nan=False),
)
positive_thresholds = thresholds.filter(lambda value: value > 0)


def _assert_issue(issue: object, feature_count: int) -> None:
    assert isinstance(issue, DatasetIssue)
    for index in (issue.feature_index, issue.related_feature_index):
        assert index is None or 0 <= index < max(feature_count, 1)
    json.dumps(issue.to_dict())


def _assert_audit_result(result: object, feature_count: int) -> None:
    assert isinstance(result, DatasetAuditResult)
    assert result.feature_count == feature_count
    assert 0 <= result.quality_score <= 100
    for issue in result.issues:
        _assert_issue(issue, feature_count)
    json.dumps(result.to_dict())


@dataclass(frozen=True, slots=True)
class RuleSettings:
    """Thresholds shared by every topology rule type in one generated case."""

    tolerance: float = 0.0
    minimum_area: float = 0.0
    minimum_length: float = 1.0
    minimum_distance: float = 1.0
    minimum_angle: float = 10.0
    allowed_geometry_types: tuple[str, ...] = ("Polygon",)
    precision_grid_size: float = 1.0
    overlap_policy: AttributeOverlapPolicy = AttributeOverlapPolicy.DENY_ALL
    use_reference: bool = True

    def rule(self, rule_type: TopologyRuleType) -> TopologyRule:
        """Build a valid rule of ``rule_type`` from these settings."""
        with_reference = rule_type in NEEDS_REFERENCE or self.use_reference
        return TopologyRule(
            rule_type,
            layer="source",
            reference_layer="reference" if with_reference else None,
            tolerance=self.tolerance,
            minimum_area=self.minimum_area,
            minimum_length=self.minimum_length,
            minimum_distance=self.minimum_distance,
            minimum_angle=self.minimum_angle,
            allowed_geometry_types=self.allowed_geometry_types,
            precision_grid_size=self.precision_grid_size,
            attribute_column="zone",
            overlap_policy=self.overlap_policy,
        )


rule_settings = st.builds(
    RuleSettings,
    tolerance=thresholds,
    minimum_area=thresholds,
    minimum_length=positive_thresholds,
    minimum_distance=positive_thresholds,
    minimum_angle=st.floats(min_value=1e-6, max_value=180),
    allowed_geometry_types=st.lists(st.sampled_from(GEOMETRY_TYPES), min_size=1, unique=True).map(
        tuple
    ),
    precision_grid_size=positive_thresholds,
    overlap_policy=st.sampled_from(AttributeOverlapPolicy),
    use_reference=st.booleans(),
)


def topology_rules(rule_type: TopologyRuleType) -> st.SearchStrategy[TopologyRule]:
    return rule_settings.map(lambda settings: settings.rule(rule_type))


def layer(name: str, *geometries_wkt: str) -> DatasetLayer:
    """A regression-example layer whose features all carry a ``zone`` attribute."""
    return DatasetLayer(name, geometries_wkt, None, tuple({"zone": 1} for _ in geometries_wkt))


@st.composite
def dataset_layers(draw: st.DrawFn, name: str) -> DatasetLayer:
    geometries = draw(dirty_layers)
    attributes = [{"zone": draw(attribute_values)} for _ in geometries]
    return DatasetLayer(
        name,
        tuple(shapely.to_wkt(item, rounding_precision=-1) for item in geometries),
        draw(st.sampled_from(CRS_CHOICES)),
        tuple(attributes),
    )


@st.composite
def attribute_rules(draw: st.DrawFn) -> AttributeRule:
    rule_type = draw(st.sampled_from(AttributeRuleType))
    column = draw(st.sampled_from(("parcel_id", "status", "missing_column")))
    if rule_type is AttributeRuleType.ALLOWED_VALUES:
        return AttributeRule(column, rule_type, allowed_values=("active", 1, 2.5, True))
    if rule_type is AttributeRuleType.NUMERIC_RANGE:
        low = draw(st.none() | st.floats(min_value=-1e6, max_value=0))
        high = draw(st.none() | st.floats(min_value=0, max_value=1e6))
        return AttributeRule(column, rule_type, minimum=low, maximum=high)
    return AttributeRule(column, rule_type)


@st.composite
def quality_profiles(draw: st.DrawFn, dataset_name: str) -> QualityProfile:
    local_types = [item for item in TopologyRuleType if item not in NEEDS_REFERENCE]
    local_rules = [
        replace(draw(topology_rules(rule_type)), layer=dataset_name, reference_layer=None)
        for rule_type in draw(st.lists(st.sampled_from(local_types), max_size=3, unique=True))
    ]
    return QualityProfile(
        name="property",
        preset=draw(st.none() | st.sampled_from(QualityPreset)),
        tolerance=draw(thresholds),
        minimum_area=draw(thresholds),
        require_crs=draw(st.booleans()),
        require_projected_crs=draw(st.booleans()),
        allowed_crs=tuple(draw(st.lists(st.sampled_from(CRS_CHOICES[1:]), unique=True))),
        id_column=draw(st.sampled_from((None, "parcel_id"))),
        enabled_checks=tuple(draw(st.lists(st.sampled_from(CHECK_NAMES), min_size=1, unique=True))),
        expected_geometry_types=tuple(
            draw(st.lists(st.sampled_from(GEOMETRY_TYPES), unique=True, max_size=3))
        ),
        topology_rules=tuple(local_rules),
        attribute_rules=tuple(draw(st.lists(attribute_rules(), max_size=4))),
    )


@pytest.mark.parametrize("preset", [None, *QualityPreset], ids=lambda item: str(item))
@given(
    geometries=dirty_layers,
    crs=st.sampled_from(CRS_CHOICES),
    tolerance=thresholds,
    minimum_area=thresholds,
)
# GEOS equals() raised on NaN coordinates in the baseline duplicate check.
@example(
    geometries=[from_wkt(NAN_POLYGON), from_wkt("POLYGON ((0 0, 0 1, 0 0))")],
    crs=None,
    tolerance=0.0,
    minimum_area=0.0,
).via("regression")
# buffer() on an all-NaN line segfaulted the point_survey tolerance duplicate check.
@example(
    geometries=[from_wkt(ALL_NAN_LINE), Point(0, 0)],
    crs=None,
    tolerance=1.0,
    minimum_area=0.0,
).via("regression")
# buffer() overflowed to NaN on coordinates near the float limit.
@example(
    geometries=[from_wkt(OVERFLOW_POLYGON), Point(0, 0)],
    crs=None,
    tolerance=2.0,
    minimum_area=0.0,
).via("regression")
# The road preset raised on any non-line feature in a mixed layer.
@example(
    geometries=[Point(0, 0), from_wkt("LINESTRING (0 0, 1 0)")],
    crs=None,
    tolerance=0.0,
    minimum_area=0.0,
).via("regression")
# The UTM suggestion unioned invalid polygons, which GEOS overlay rejects.
@example(
    geometries=[from_wkt(BOWTIE), from_wkt("POLYGON ((0 0, 2 2, 0 2, 2 0, 0 0))")],
    crs="EPSG:4326",
    tolerance=0.0,
    minimum_area=0.0,
).via("regression")
# The UTM suggestion took the centroid of a NaN union and read X from an empty point.
@example(
    geometries=[from_wkt("LINESTRING (0 0, NaN 1)")],
    crs="EPSG:4326",
    tolerance=0.0,
    minimum_area=0.0,
).via("regression")
def test_geometry_audit_never_crashes(
    preset: QualityPreset | None,
    geometries: Sequence[BaseGeometry],
    crs: str | None,
    tolerance: float,
    minimum_area: float,
) -> None:
    result = audit_geometries(
        geometries,
        preset=preset,
        crs=crs,
        tolerance=tolerance,
        minimum_area=minimum_area,
    )

    _assert_audit_result(result, len(geometries))


@pytest.mark.parametrize("rule_type", list(TopologyRuleType), ids=lambda item: item.value)
@given(
    settings=rule_settings,
    source=dataset_layers("source"),
    reference=dataset_layers("reference"),
)
# Each example runs against every rule type.
# buffer() on an all-NaN line segfaulted no_duplicate, must_be_inside, and must_cover.
@example(
    settings=RuleSettings(tolerance=1.0),
    source=layer("source", ALL_NAN_LINE, "POINT (0 0)"),
    reference=layer("reference", ALL_NAN_LINE, "POINT (0 0)"),
).via("regression")
# GEOS predicates raised on NaN polygons in relation, boundary, and overlap rules.
@example(
    settings=RuleSettings(tolerance=1.0),
    source=layer("source", "POLYGON ((0 0, NaN 0, 0 0))", "POINT (0 0)"),
    reference=layer("reference", NAN_POLYGON, "POLYGON ((0 0, 0 1, 0 0, 0 1, 0 0))"),
).via("regression")
# buffer() overflowed to NaN on coordinates near the float limit.
@example(
    settings=RuleSettings(tolerance=2.0),
    source=layer("source", OVERFLOW_POLYGON, "POINT (0 0)"),
    reference=layer("reference", OVERFLOW_POLYGON, "POINT (0 0)"),
).via("regression")
# Overlays in must_not_intersect, attribute_overlap, and boundary_must_match
# raised on a self-intersecting polygon.
@example(
    settings=RuleSettings(),
    source=layer("source", BOWTIE, "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))"),
    reference=layer("reference", "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))", BOWTIE),
).via("regression")
# Overshoot/undershoot intersected a collapsed line.
@example(
    settings=RuleSettings(tolerance=1.0, use_reference=False),
    source=layer("source", "LINESTRING (0 0, 0 0)", "LINESTRING (0 0, 1 0)"),
    reference=layer("reference"),
).via("regression")
# Empty parts reached code that indexes the first coordinate (dangles, endpoints,
# overshoot, spikes, vertex distance); a GeometryCollection has no boundary; and
# attribute_overlap rejected an empty layer as missing its attribute.
@example(
    settings=RuleSettings(tolerance=1.0),
    source=layer("source", "LINESTRING EMPTY", "POLYGON EMPTY", "LINESTRING (0 0, 1 0)"),
    reference=layer("reference", "POINT (0 0)"),
).via("regression")
@example(
    settings=RuleSettings(),
    source=layer("source", "GEOMETRYCOLLECTION (POINT (0 0))"),
    reference=layer("reference", "POINT (0 0)"),
).via("regression")
@example(
    settings=RuleSettings(use_reference=False),
    source=layer("source"),
    reference=layer("reference"),
).via("regression")
# Overshoot/undershoot projected onto a line whose length underflows.
@example(
    settings=RuleSettings(tolerance=1e-12, use_reference=False),
    source=layer("source", "LINESTRING (0 0, 5e-324 0)", "LINESTRING (0 0, 0 0, 0 0, 0 1)"),
    reference=layer("reference"),
).via("regression")
# precision_grid rounded NaN coordinates and overflowed dividing near-limit ones.
@example(
    settings=RuleSettings(precision_grid_size=0.5),
    source=layer("source", "POINT (NaN 0)", "POINT (1.7976931348623157e308 0)"),
    reference=layer("reference"),
).via("regression")
# Overshoot/undershoot intersected all-NaN multilines.
@example(
    settings=RuleSettings(tolerance=1e-12, use_reference=False),
    source=layer("source", "MULTILINESTRING ((NaN NaN, NaN NaN), (NaN NaN, NaN NaN))"),
    reference=layer("reference"),
).via("regression")
def test_topology_rule_never_crashes(
    rule_type: TopologyRuleType,
    settings: RuleSettings,
    source: DatasetLayer,
    reference: DatasetLayer,
) -> None:
    issues = evaluate_topology_rules((source, reference), (settings.rule(rule_type),))

    assert isinstance(issues, tuple)
    for issue in issues:
        _assert_issue(issue, max(len(source.geometries_wkt), len(reference.geometries_wkt)))


@given(data=st.data())
def test_dataset_checks_never_crash(data: st.DataObject) -> None:
    geometries = data.draw(dirty_layers)
    frame = gpd.GeoDataFrame(
        {
            "parcel_id": [data.draw(attribute_values) for _ in geometries],
            "status": [data.draw(attribute_values) for _ in geometries],
        },
        geometry=gpd.GeoSeries(list(geometries), dtype="geometry"),
        crs=data.draw(st.sampled_from(CRS_CHOICES)),
    )
    profile = data.draw(st.none() | quality_profiles("parcels"))

    result = audit_geodataframe(frame, dataset_name="parcels", profile=profile)
    checks = _checks_for_result(result, profile)

    _assert_audit_result(replace(result, checks=checks), len(geometries))
    assert tuple(check.name for check in checks) == CHECK_NAMES
    for check in checks:
        assert isinstance(check, AuditCheckResult)
        assert isinstance(check.status, CheckStatus)


@given(geometry=dirty_geometries)
def test_geometry_validator_never_crashes(geometry: BaseGeometry) -> None:
    result = ShapelyGeometryValidator().validate(geometry)

    assert isinstance(result, GeometryValidationResult)
    assert result.is_valid == (not result.issues)


@given(cells=st.lists(dirty_wkb_cells, max_size=8), offset=st.integers(0, 10_000))
def test_streaming_geometry_check_never_crashes(cells: list[bytes | None], offset: int) -> None:
    batch = pa.record_batch({"geometry": pa.array(cells, type=pa.binary())})
    metadata = DatasetMetadata("Parquet", None, "EPSG:3857", len(cells), "geometry")

    result = GeometryChunkProcessor(ShapelyGeometryValidator()).process(
        FeatureChunk(offset, batch, len(cells)), metadata
    )

    assert isinstance(result, GeometryChunkResult)
    assert result.feature_count == len(cells)
    assert result.invalid_feature_count == len(result.findings)
    assert all(offset <= item.feature_index < offset + len(cells) for item in result.findings)


@given(geometries=dirty_layers)
def test_registered_domain_rules_never_crash(geometries: Sequence[BaseGeometry]) -> None:
    registry: RuleRegistry[Sequence[BaseGeometry]] = RuleRegistry((NonEmptyRule(),))

    report = RuleEngine(registry, error_policy=ErrorPolicy.RAISE).execute(geometries)

    assert len(report.results) == len(registry)
    assert all(item.status is not ResultStatus.ERROR for item in report.results)


def test_every_registered_check_is_covered() -> None:
    """Fail loudly when a dataset check is registered without updating this suite.

    Topology, attribute, and preset rules are parametrized or sampled from their
    enums, so new members are picked up automatically.
    """
    assert QualityProfile(name="all").enabled_checks == CHECK_NAMES
