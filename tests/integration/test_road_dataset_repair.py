"""File-to-file integration tests for road topology repair."""

from pathlib import Path

import geopandas as gpd  # type: ignore[import-untyped]
import pytest
from shapely.geometry import LineString, Point

from geoqc.domain.models.spatial_intelligence import RoadNetworkRepairConfig
from geoqc.infrastructure.gis.road_dataset_repair import RoadDatasetRepairer


def _roads(crs: str = "EPSG:3857") -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"name": ["east-west", "north-south", "gap"]},
        geometry=[
            LineString([(0, 0), (2, 0)]),
            LineString([(1, -1), (1, 1)]),
            LineString([(2.05, 0), (3, 0)]),
        ],
        crs=crs,
    )


def test_repair_dataset_writes_atomic_geopackage_with_attributes(tmp_path: Path) -> None:
    source = tmp_path / "roads.geojson"
    output = tmp_path / "nested" / "repaired.gpkg"
    _roads().to_file(source, driver="GeoJSON")

    result = RoadDatasetRepairer().repair(
        source,
        output,
        RoadNetworkRepairConfig(snap_tolerance=0.1),
        output_layer="network",
    )

    repaired = gpd.read_file(output, layer="network")
    assert result.input_feature_count == 3
    assert result.snapped_endpoint_count == 1
    assert result.output_segment_count == 5
    assert len(repaired) == 5
    assert set(repaired["name"]) == {"east-west", "north-south", "gap"}
    assert repaired.crs == _roads().crs
    assert {"_geoqc_segment", "_geoqc_sources", "_geoqc_length", "_geoqc_layer"} <= set(
        repaired.columns
    )
    assert result.to_dict()["output_layer"] == "network"


def test_repair_dataset_requires_layer_for_multilayer_geopackage(tmp_path: Path) -> None:
    source = tmp_path / "roads.gpkg"
    _roads().to_file(source, layer="first", driver="GPKG")
    _roads().to_file(source, layer="second", driver="GPKG", append=True)

    with pytest.raises(ValueError, match="multiple layers"):
        RoadDatasetRepairer().repair(source, tmp_path / "out.gpkg", RoadNetworkRepairConfig())

    result = RoadDatasetRepairer().repair(
        source,
        tmp_path / "out.gpkg",
        RoadNetworkRepairConfig(),
        layer="second",
    )
    assert result.source_layer == "second"


def test_repair_dataset_rejects_unsafe_or_ambiguous_requests(tmp_path: Path) -> None:
    source = tmp_path / "roads.geojson"
    _roads().to_file(source, driver="GeoJSON")
    repairer = RoadDatasetRepairer()
    config = RoadNetworkRepairConfig()

    gpkg_source = tmp_path / "roads.gpkg"
    _roads().to_file(gpkg_source, driver="GPKG")
    with pytest.raises(ValueError, match="must not overwrite"):
        repairer.repair(gpkg_source, gpkg_source, config)
    with pytest.raises(ValueError, match=".gpkg"):
        repairer.repair(source, tmp_path / "out.geojson", config)
    with pytest.raises(ValueError, match="only for GeoPackage"):
        repairer.repair(source, tmp_path / "out.gpkg", config, layer="roads")
    with pytest.raises(FileNotFoundError):
        repairer.repair(tmp_path / "missing.shp", tmp_path / "out.gpkg", config)
    with pytest.raises(ValueError, match="positive"):
        repairer.repair(source, tmp_path / "out.gpkg", config, max_features=0)

    existing = tmp_path / "existing.gpkg"
    existing.touch()
    with pytest.raises(FileExistsError):
        repairer.repair(source, existing, config)


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        (gpd.GeoDataFrame(geometry=[Point(0, 0)], crs="EPSG:3857"), "only LineString"),
        (gpd.GeoDataFrame(geometry=[None], crs="EPSG:3857"), "null or empty"),
        (gpd.GeoDataFrame(geometry=[LineString([(0, 0), (1, 0)])]), "known CRS"),
    ],
)
def test_repair_dataset_rejects_invalid_content(
    tmp_path: Path, frame: gpd.GeoDataFrame, message: str
) -> None:
    source = tmp_path / "invalid.gpkg"
    frame.to_file(source, driver="GPKG")

    with pytest.raises(ValueError, match=message):
        RoadDatasetRepairer().repair(source, tmp_path / "out.gpkg", RoadNetworkRepairConfig())


def test_repair_dataset_guards_geographic_snapping(tmp_path: Path) -> None:
    source = tmp_path / "roads.geojson"
    _roads("EPSG:4326").to_file(source, driver="GeoJSON")
    config = RoadNetworkRepairConfig(snap_tolerance=0.1)

    with pytest.raises(ValueError, match="geographic CRS"):
        RoadDatasetRepairer().repair(source, tmp_path / "out.gpkg", config)

    result = RoadDatasetRepairer().repair(
        source,
        tmp_path / "out.gpkg",
        config,
        allow_geographic=True,
    )
    assert result.output_segment_count == 5


def test_repair_dataset_rejects_reserved_columns_and_empty_result(tmp_path: Path) -> None:
    source = tmp_path / "roads.geojson"
    frame = _roads()
    frame["_geoqc_segment"] = 99
    frame.to_file(source, driver="GeoJSON")

    with pytest.raises(ValueError, match="reserved GeoQC columns"):
        RoadDatasetRepairer().repair(source, tmp_path / "out.gpkg", RoadNetworkRepairConfig())

    clean_source = tmp_path / "clean.geojson"
    _roads().to_file(clean_source, driver="GeoJSON")
    with pytest.raises(ValueError, match="No road segments remain"):
        RoadDatasetRepairer().repair(
            clean_source,
            tmp_path / "out.gpkg",
            RoadNetworkRepairConfig(minimum_segment_length=100),
        )
