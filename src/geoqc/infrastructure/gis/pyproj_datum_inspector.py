"""PyProj adapter for datum operation inspection and grid shift sampling."""

import warnings
from collections.abc import Sequence
from math import isfinite
from typing import Any, cast

from pyproj import CRS, Geod
from pyproj.aoi import AreaOfInterest
from pyproj.exceptions import CRSError, ProjError
from pyproj.transformer import TransformerGroup

from geoqc.domain.exceptions import DatumTransformationError
from geoqc.domain.models import (
    DatumShiftSample,
    DatumTransformationEvidence,
    GeographicBounds,
)


class PyprojDatumTransformationInspector:
    """Measure geographic datum shifts using the best local PyProj operation."""

    def inspect(
        self,
        source_crs: str,
        target_crs: str,
        area: GeographicBounds,
        sample_points: Sequence[tuple[float, float]],
    ) -> DatumTransformationEvidence:
        """Inspect operation quality and calculate geodesic sample displacement."""
        try:
            source = CRS.from_user_input(source_crs)
            target = CRS.from_user_input(target_crs)
            source_geodetic = source.geodetic_crs
            target_geodetic = target.geodetic_crs
            if source_geodetic is None or target_geodetic is None:
                raise DatumTransformationError("CRS must have a geodetic component")

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                group = TransformerGroup(
                    source_geodetic,
                    target_geodetic,
                    always_xy=True,
                    area_of_interest=cast(
                        Any,
                        AreaOfInterest(
                            area.west,
                            area.south,
                            area.east,
                            area.north,
                        ),
                    ),
                    allow_ballpark=True,
                )
            if not group.transformers:
                raise DatumTransformationError("No transformation operation is available")

            transformer = group.transformers[0]
            transformed = transformer.transform(
                [point[0] for point in sample_points],
                [point[1] for point in sample_points],
                errcheck=True,
            )
            longitudes, latitudes = transformed[0], transformed[1]
            geod = target_geodetic.get_geod()
            if geod is None:
                raise DatumTransformationError("Target CRS has no usable ellipsoid")
            samples = tuple(
                self._sample(geod, point, shifted)
                for point, shifted in zip(
                    sample_points,
                    zip(longitudes, latitudes, strict=True),
                    strict=True,
                )
            )
        except DatumTransformationError:
            raise
        except (CRSError, ProjError, ValueError) as error:
            raise DatumTransformationError(str(error)) from error

        return DatumTransformationEvidence(
            source_crs=self._name(source_geodetic),
            target_crs=self._name(target_geodetic),
            operation_name=transformer.description,
            declared_accuracy_m=(transformer.accuracy if transformer.accuracy >= 0 else None),
            best_operation_available=group.best_available,
            uses_ballpark_transformation=any(
                operation.has_ballpark_transformation
                for operation in (transformer.operations or ())
            ),
            missing_grids=self._missing_grids(group),
            samples=samples,
        )

    @staticmethod
    def _sample(
        geod: Geod,
        point: tuple[float, float],
        shifted: tuple[float, float],
    ) -> DatumShiftSample:
        if not all(isfinite(value) for value in shifted):
            raise DatumTransformationError("Transformation produced a non-finite coordinate")
        _, _, distance = geod.inv(point[0], point[1], shifted[0], shifted[1])
        return DatumShiftSample(point[0], point[1], shifted[0], shifted[1], abs(distance))

    @staticmethod
    def _missing_grids(group: TransformerGroup) -> tuple[str, ...]:
        if group.best_available or not group.unavailable_operations:
            return ()
        best_unavailable = group.unavailable_operations[0]
        return tuple(
            dict.fromkeys(grid.short_name for grid in best_unavailable.grids if not grid.available)
        )

    @staticmethod
    def _name(crs: CRS) -> str:
        authority = crs.to_authority()
        return f"{authority[0]}:{authority[1]}" if authority else crs.name
