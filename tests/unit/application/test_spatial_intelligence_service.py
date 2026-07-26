from unittest.mock import Mock

from geoqc.application.services.spatial_intelligence import (
    BoundarySnapService,
    RoadNetworkService,
    SmallPolygonService,
)
from geoqc.domain.models.spatial_intelligence import (
    BoundarySnapConfig,
    BoundarySnapResult,
    RoadNetworkConfig,
    RoadNetworkReport,
    SmallPolygonConfig,
    SmallPolygonReport,
)


def test_boundary_service_delegates_with_default_and_explicit_config() -> None:
    engine = Mock()
    expected = BoundarySnapResult((), 0)
    engine.snap.return_value = expected
    service = BoundarySnapService(engine)

    assert service.preview(["POLYGON EMPTY"]) is expected
    assert isinstance(engine.snap.call_args.args[1], BoundarySnapConfig)
    config = BoundarySnapConfig(tolerance=0.25)
    assert service.preview([], config) is expected
    assert engine.snap.call_args.args == ([], config)


def test_road_service_delegates_with_default_config() -> None:
    engine = Mock()
    expected = RoadNetworkReport(0, ())
    engine.analyze.return_value = expected

    assert RoadNetworkService(engine).analyze([]) is expected
    assert isinstance(engine.analyze.call_args.args[1], RoadNetworkConfig)


def test_small_polygon_service_delegates_with_default_config() -> None:
    engine = Mock()
    expected = SmallPolygonReport(0, ())
    engine.analyze.return_value = expected

    assert SmallPolygonService(engine).preview([]) is expected
    assert isinstance(engine.analyze.call_args.args[1], SmallPolygonConfig)
