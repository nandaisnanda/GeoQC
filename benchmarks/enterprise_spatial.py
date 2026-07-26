"""Repeatable scalability benchmark for indexed duplicate detection."""

from __future__ import annotations

import argparse
from time import perf_counter

from shapely.geometry import box

from geoqc import SpatialDuplicateConfig, detect_spatial_duplicates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=int, default=10_000)
    args = parser.parse_args()
    geometries = [box(index * 2, 0, index * 2 + 1, 1) for index in range(args.features)]
    geometries.extend(geometries[index] for index in range(0, args.features, 1000))
    started = perf_counter()
    report = detect_spatial_duplicates(
        geometries, SpatialDuplicateConfig(similarity_threshold=0.99)
    )
    elapsed = perf_counter() - started
    print(
        f"features={len(geometries)} duplicates={report.duplicate_count} "
        f"candidates={report.candidate_pairs}/{report.possible_pairs} "
        f"reduction={report.candidate_reduction_percent:.4f}% elapsed={elapsed:.3f}s"
    )


if __name__ == "__main__":
    main()
