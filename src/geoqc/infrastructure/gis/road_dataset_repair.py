"""Safe file-to-file road topology repair using GeoPandas and Pyogrio."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import geopandas as gpd  # type: ignore[import-untyped]
import pyogrio  # type: ignore[import-untyped]
import shapely

from geoqc.domain.models.spatial_intelligence import (
    RoadNetworkRepairConfig,
    RoadRepairSegment,
)
from geoqc.infrastructure.gis.shapely_spatial_intelligence import (
    ShapelyRoadNetworkRepairer,
)

_SUPPORTED_INPUT_SUFFIXES = frozenset({".fgb", ".geojson", ".gpkg", ".json", ".shp"})
_AUDIT_COLUMNS = frozenset(
    {"_geoqc_segment", "_geoqc_sources", "_geoqc_length", "_geoqc_layer"}
)


@dataclass(frozen=True, slots=True)
class RoadDatasetRepairResult:
    """Summary of a persisted road-network repair."""

    source: Path
    source_layer: str | None
    output: Path
    output_layer: str
    crs: str
    input_feature_count: int
    input_part_count: int
    snapped_endpoint_count: int
    output_segment_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "source": str(self.source),
            "source_layer": self.source_layer,
            "output": str(self.output),
            "output_layer": self.output_layer,
            "crs": self.crs,
            "input_feature_count": self.input_feature_count,
            "input_part_count": self.input_part_count,
            "snapped_endpoint_count": self.snapped_endpoint_count,
            "output_segment_count": self.output_segment_count,
        }


class RoadDatasetRepairer:
    """Read a vector layer, repair it, and atomically write a GeoPackage."""

    def __init__(self, engine: ShapelyRoadNetworkRepairer | None = None) -> None:
        self._engine = engine or ShapelyRoadNetworkRepairer()

    def repair(
        self,
        source: Path,
        output: Path,
        config: RoadNetworkRepairConfig,
        *,
        layer: str | None = None,
        output_layer: str = "repaired_roads",
        overwrite: bool = False,
        allow_geographic: bool = False,
        max_features: int = 500_000,
    ) -> RoadDatasetRepairResult:
        source = source.resolve()
        output = output.resolve()
        selected_layer = self._validate_request(
            source,
            output,
            layer,
            output_layer,
            overwrite=overwrite,
            max_features=max_features,
        )
        frame = gpd.read_file(source, layer=selected_layer)
        if len(frame) > max_features:
            raise ValueError(
                f"Input has {len(frame)} features; maximum is {max_features}."
            )
        if frame.empty:
            raise ValueError("Input layer contains no features.")
        if frame.geometry.isna().any() or frame.geometry.is_empty.any():
            raise ValueError("Input layer contains null or empty geometries.")
        geometry_types = set(frame.geom_type)
        if not geometry_types <= {"LineString", "MultiLineString"}:
            raise ValueError(
                "Road repair accepts only LineString and MultiLineString geometries; "
                f"found {sorted(geometry_types)}."
            )
        if frame.crs is None:
            raise ValueError("Input layer must have a known CRS.")
        collisions = _AUDIT_COLUMNS.intersection(frame.columns)
        if collisions:
            raise ValueError(
                f"Input already contains reserved GeoQC columns: {sorted(collisions)}."
            )
        if config.snap_tolerance > 0 and frame.crs.is_geographic and not allow_geographic:
            raise ValueError(
                "Endpoint snapping on a geographic CRS uses degrees. Reproject to a projected "
                "CRS or pass allow_geographic=True explicitly."
            )

        frame = frame.reset_index(drop=True)
        repair = self._engine.repair(
            [str(shapely.to_wkt(item, rounding_precision=-1)) for item in frame.geometry],
            config,
        )
        if not repair.segments:
            raise ValueError(
                "No road segments remain after applying the configured minimum length."
            )
        repaired = self._restore_attributes(
            frame, repair.segments, selected_layer or source.stem
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.stem}.{uuid4().hex}.gpkg")
        try:
            repaired.to_file(temporary, layer=output_layer, driver="GPKG")
            temporary.replace(output)
        finally:
            if temporary.exists():
                temporary.unlink()

        return RoadDatasetRepairResult(
            source=source,
            source_layer=selected_layer,
            output=output,
            output_layer=output_layer,
            crs=str(frame.crs),
            input_feature_count=repair.input_feature_count,
            input_part_count=repair.input_part_count,
            snapped_endpoint_count=repair.snapped_endpoint_count,
            output_segment_count=repair.output_segment_count,
        )

    @staticmethod
    def _validate_request(
        source: Path,
        output: Path,
        layer: str | None,
        output_layer: str,
        *,
        overwrite: bool,
        max_features: int,
    ) -> str | None:
        if not source.is_file():
            raise FileNotFoundError(f"Input dataset does not exist: {source}")
        if source.suffix.casefold() not in _SUPPORTED_INPUT_SUFFIXES:
            supported = ", ".join(sorted(_SUPPORTED_INPUT_SUFFIXES))
            raise ValueError(f"Unsupported input format. Expected one of: {supported}.")
        if output.suffix.casefold() != ".gpkg":
            raise ValueError("Road repair output must use the .gpkg extension.")
        if source == output:
            raise ValueError("Output must not overwrite the source dataset.")
        if output.exists() and not overwrite:
            raise FileExistsError(f"Output already exists: {output}")
        if not output_layer.strip() or "\x00" in output_layer:
            raise ValueError("Output layer name must be non-empty and contain no NUL byte.")
        if max_features < 1:
            raise ValueError("max_features must be positive.")

        if source.suffix.casefold() != ".gpkg":
            if layer is not None:
                raise ValueError("The layer option is supported only for GeoPackage input.")
            return None
        layers = [str(row[0]) for row in pyogrio.list_layers(source)]
        if layer is not None:
            if layer not in layers:
                raise ValueError(f"Layer {layer!r} was not found. Available: {layers}.")
            return layer
        if len(layers) != 1:
            raise ValueError(f"GeoPackage has multiple layers; choose one from: {layers}.")
        return layers[0]

    @staticmethod
    def _restore_attributes(
        source: gpd.GeoDataFrame,
        segments: tuple[RoadRepairSegment, ...],
        source_layer: str,
    ) -> gpd.GeoDataFrame:
        records: list[dict[str, object]] = []
        attribute_columns = [column for column in source.columns if column != source.geometry.name]
        for item in segments:
            source_indices = item.source_indices
            primary = int(source_indices[0])
            row = source.iloc[primary]
            record = {column: row[column] for column in attribute_columns}
            record.update(
                {
                    "_geoqc_segment": item.segment_index,
                    "_geoqc_sources": ",".join(str(index) for index in source_indices),
                    "_geoqc_length": item.length,
                    "_geoqc_layer": source_layer,
                    "geometry": shapely.from_wkt(item.geometry_wkt),
                }
            )
            records.append(record)
        return gpd.GeoDataFrame(records, geometry="geometry", crs=source.crs)
