"""Repair the bundled road test data and write an auditable GeoPackage.

This is a real-data acceptance workflow, not a synthetic benchmark. It keeps
the source Shapefiles untouched and writes all artifacts below the requested
output directory.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4

import geopandas as gpd
import pandas as pd
import shapely
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

import geoqc


def _line_parts(geometries: list[BaseGeometry]) -> list[LineString]:
    parts: list[LineString] = []
    for geometry in geometries:
        if isinstance(geometry, LineString):
            parts.append(geometry)
        elif isinstance(geometry, MultiLineString):
            parts.extend(geometry.geoms)
    return parts


def _is_endpoint(line: LineString, point: Point, tolerance: float = 1e-8) -> bool:
    return point.distance(Point(line.coords[0])) <= tolerance or point.distance(
        Point(line.coords[-1])
    ) <= tolerance


def _point_parts(geometry: BaseGeometry) -> list[Point]:
    if isinstance(geometry, Point):
        return [geometry]
    if geometry.geom_type in {"MultiPoint", "GeometryCollection"}:
        return [part for part in geometry.geoms if isinstance(part, Point)]
    return []


def audit_linework(geometries: list[BaseGeometry], snap_tolerance: float) -> dict[str, Any]:
    lines = _line_parts(geometries)
    tree = STRtree(lines)
    unnoded_pairs = 0
    overlap_pairs = 0
    for left, line in enumerate(lines):
        for candidate in tree.query(line):
            right = int(candidate)
            if right <= left:
                continue
            other = lines[right]
            intersection = line.intersection(other)
            if intersection.is_empty:
                continue
            if intersection.length > 1e-8:
                overlap_pairs += 1
                continue
            points = _point_parts(intersection)
            if any(
                not (_is_endpoint(line, point) and _is_endpoint(other, point))
                for point in points
            ):
                unnoded_pairs += 1

    near_gap_endpoints = 0
    endpoint_points = [
        Point(coordinate)
        for line in lines
        for coordinate in (line.coords[0], line.coords[-1])
    ]
    endpoint_tree = STRtree(endpoint_points)
    dead_end_endpoints = sum(
        sum(
            point.distance(endpoint_points[int(candidate)]) <= 1e-8
            for candidate in endpoint_tree.query(point.buffer(1e-8))
        )
        == 1
        for point in endpoint_points
    )
    for line_index, line in enumerate(lines):
        for coordinate in (line.coords[0], line.coords[-1]):
            point = Point(coordinate)
            nearby = [
                int(candidate)
                for candidate in tree.query(point.buffer(snap_tolerance))
                if int(candidate) != line_index
            ]
            if not nearby:
                continue
            distances = [point.distance(lines[item]) for item in nearby]
            nearest = min(distances)
            if 1e-8 < nearest <= snap_tolerance:
                near_gap_endpoints += 1

    normalized = [shapely.to_wkb(shapely.normalize(line), output_dimension=2) for line in lines]
    duplicate_segments = sum(count - 1 for count in Counter(normalized).values() if count > 1)
    return {
        "feature_count": len(geometries),
        "line_part_count": len(lines),
        "invalid_feature_count": sum(not geometry.is_valid for geometry in geometries),
        "non_simple_feature_count": sum(not geometry.is_simple for geometry in geometries),
        "unnoded_intersection_pair_count": unnoded_pairs,
        "linear_overlap_pair_count": overlap_pairs,
        "near_gap_endpoint_count": near_gap_endpoints,
        "dead_end_endpoint_count": dead_end_endpoints,
        "sub_meter_line_part_count": sum(line.length < 1.0 for line in lines),
        "exact_duplicate_segment_count": duplicate_segments,
        "total_length": sum(line.length for line in lines),
        "minimum_segment_length": min((line.length for line in lines), default=0.0),
    }


def _load_sources(input_dir: Path) -> tuple[gpd.GeoDataFrame, list[dict[str, Any]]]:
    frames: list[gpd.GeoDataFrame] = []
    summaries: list[dict[str, Any]] = []
    crs = None
    feature_offset = 0
    for path in sorted(input_dir.glob("*.shp")):
        frame = gpd.read_file(path)
        if crs is None:
            crs = frame.crs
        elif frame.crs != crs:
            raise ValueError(f"CRS mismatch: {path.name} uses {frame.crs}, expected {crs}")
        if not all(item in {"LineString", "MultiLineString"} for item in frame.geom_type):
            raise ValueError(f"{path.name} contains non-line geometries")
        frame = frame.copy()
        frame["source_layer"] = path.stem
        frame["source_fid"] = range(len(frame))
        frame["source_index"] = range(feature_offset, feature_offset + len(frame))
        feature_offset += len(frame)
        summaries.append(
            {
                "file": path.name,
                "feature_count": len(frame),
                "geometry_types": frame.geom_type.value_counts().to_dict(),
                "crs": str(frame.crs),
            }
        )
        frames.append(frame)
    if not frames:
        raise ValueError(f"No Shapefiles found in {input_dir}")
    combined = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=crs)
    return combined, summaries


def _build_output(
    sources: gpd.GeoDataFrame, result: geoqc.RoadNetworkRepairResult
) -> gpd.GeoDataFrame:
    records: list[dict[str, Any]] = []
    attribute_columns = [column for column in sources.columns if column != "geometry"]
    for segment in result.segments:
        primary = segment.source_indices[0]
        source = sources.iloc[primary]
        record = {column: source[column] for column in attribute_columns}
        record.update(
            {
                "segment_id": segment.segment_index,
                "source_ids": ",".join(str(item) for item in segment.source_indices),
                "repaired_length": segment.length,
                "geometry": shapely.from_wkt(segment.geometry_wkt),
            }
        )
        records.append(record)
    return gpd.GeoDataFrame(records, geometry="geometry", crs=sources.crs)


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    before = report["audit_before"]
    after = report["audit_after"]
    repair = report["repair"]
    table_rows = [
        ("Input/output features", "feature_count"),
        ("Line parts", "line_part_count"),
        ("Invalid features", "invalid_feature_count"),
        ("Non-simple features", "non_simple_feature_count"),
        ("Unnoded intersection pairs", "unnoded_intersection_pair_count"),
        ("Linear-overlap pairs", "linear_overlap_pair_count"),
        ("Near-gap endpoints", "near_gap_endpoint_count"),
        ("Dead-end endpoints (manual review)", "dead_end_endpoint_count"),
        ("Sub-metre line parts (retained)", "sub_meter_line_part_count"),
        ("Exact duplicate segments", "exact_duplicate_segment_count"),
    ]
    table = "\n".join(
        f"| {label} | {before[key]} | {after[key]} |" for label, key in table_rows
    )
    text = f"""# GeoQC testdata topology repair

The source Shapefiles were not overwritten. The repaired network is stored in
`geoqc_testdata_repaired.gpkg` in its original projected CRS.

## Configuration

- CRS: `{report['crs']}`
- Endpoint snap tolerance: {report['config']['snap_tolerance']} metre
- Minimum retained segment length: {report['config']['minimum_segment_length']} metre

## Result

| Check | Before | After |
| --- | ---: | ---: |
{table}

The repair snapped {repair['snapped_endpoint_count']} endpoints and produced
{repair['output_segment_count']} fully noded segments from
{repair['input_part_count']} source line parts. `network_all` contains the full
network; the three named layers contain the same repaired segments grouped by
their source road class. Attributes come from the primary source feature and
`source_ids` retains complete provenance.

Dead ends are not automatically deleted: many are legitimate road termini and
need semantic/manual review. Very short valid segments are also retained unless
they are below the explicit minimum length.
"""
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("testdata"))
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/testdata_topology_repair")
    )
    parser.add_argument("--snap-tolerance", type=float, default=0.1)
    parser.add_argument("--minimum-segment-length", type=float, default=1e-8)
    args = parser.parse_args()

    sources, source_summaries = _load_sources(args.input)
    config = geoqc.RoadNetworkRepairConfig(
        snap_tolerance=args.snap_tolerance,
        minimum_segment_length=args.minimum_segment_length,
    )
    before = audit_linework(list(sources.geometry), args.snap_tolerance)
    result = geoqc.repair_road_network(list(sources.geometry), config)
    repaired = _build_output(sources, result)
    after = audit_linework(list(repaired.geometry), args.snap_tolerance)

    args.output.mkdir(parents=True, exist_ok=True)
    gpkg = args.output / "geoqc_testdata_repaired.gpkg"
    temporary_gpkg = args.output / f".geoqc-repair-{uuid4().hex}.gpkg"
    try:
        repaired.to_file(temporary_gpkg, layer="network_all", driver="GPKG")
        for layer_name in sorted(repaired["source_layer"].unique()):
            repaired.loc[repaired["source_layer"] == layer_name].to_file(
                temporary_gpkg, layer=layer_name, driver="GPKG"
            )
        temporary_gpkg.replace(gpkg)
    finally:
        if temporary_gpkg.exists():
            temporary_gpkg.unlink()

    report = {
        "source": str(args.input.resolve()),
        "output": str(gpkg.resolve()),
        "crs": str(sources.crs),
        "source_layers": source_summaries,
        "config": {
            "snap_tolerance": config.snap_tolerance,
            "minimum_segment_length": config.minimum_segment_length,
        },
        "repair": {
            "input_feature_count": result.input_feature_count,
            "input_part_count": result.input_part_count,
            "snapped_endpoint_count": result.snapped_endpoint_count,
            "output_segment_count": result.output_segment_count,
        },
        "audit_before": before,
        "audit_after": after,
        "verification_passed": all(
            after[key] == 0
            for key in (
                "invalid_feature_count",
                "non_simple_feature_count",
                "unnoded_intersection_pair_count",
                "linear_overlap_pair_count",
                "near_gap_endpoint_count",
                "exact_duplicate_segment_count",
            )
        ),
    }
    (args.output / "topology_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_markdown(report, args.output / "README.md")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
