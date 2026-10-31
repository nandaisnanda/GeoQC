from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import geopandas as gpd  # type: ignore[import-untyped]
from shapely.geometry import Polygon

RUN_CHECK = Path(__file__).parents[2] / "tools" / "validation" / "run_check.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_check", RUN_CHECK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bowtie_frame(crs: str | None) -> gpd.GeoDataFrame:
    bowtie = Polygon([(430000, 9140000), (430040, 9140040), (430040, 9140000), (430000, 9140040)])
    return gpd.GeoDataFrame(geometry=[bowtie], crs=crs)


def test_review_gpkg_opens_as_point_layer(tmp_path: Path) -> None:
    run_check = _load()
    data = tmp_path / "data"
    data.mkdir()
    _bowtie_frame("EPSG:32749").to_file(data / "parcels.gpkg", layer="parcels", driver="GPKG")

    frame = run_check.collect(data, per_code=5, seed=1)
    out = tmp_path / "review.gpkg"
    run_check.write_dataframe(frame, out, layer="review", driver="GPKG")

    review = gpd.read_file(out, layer="review")
    assert len(review) > 0
    assert set(review.geom_type) == {"Point"}
    assert review.crs.to_epsg() == 4326
    assert {"x", "y"} <= set(review.columns)
    assert review.geometry.x.between(100, 120).all()
    assert review["x"].between(430000, 430040).all()


def test_review_without_crs_keeps_xy_and_no_geometry(tmp_path: Path) -> None:
    run_check = _load()
    data = tmp_path / "data"
    data.mkdir()
    _bowtie_frame(None).to_file(data / "nocrs.gpkg", layer="nocrs", driver="GPKG")

    frame = run_check.collect(data, per_code=5, seed=1)

    assert len(frame) > 0
    assert frame.geometry.isna().all()
    assert frame["x"].notna().all()
    assert frame["y"].notna().all()
