"""End-to-end GeoQC field test on real OpenStreetMap buildings in Menteng.

A random 2 km x 2 km window (4 km2) is drawn inside the Menteng subdistrict of
Jakarta Pusat and every ``building`` way inside it is pulled from Overpass. The
data is reprojected to UTM 48S so all thresholds are in metres, audited with
GeoQC as-is, repaired as a single topological coverage, then audited again.

Nothing is injected or mocked: every defect reported here already exists in the
public OSM database. Outputs are before/after ESRI Shapefiles, before/after JPG
maps with a zoomed inset on the worst defect cluster, and a JSON audit report.
"""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib.pyplot as plt
import shapely
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry

from geoqc import (
    RepairConfig,
    RepairSession,
    ShapelyTopologyRepairer,
    SmallPolygonConfig,
    analyze_small_polygons,
    detect_spatial_duplicates,
    validate_geometry,
)

OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
# Menteng subdistrict envelope (south, west, north, east) in EPSG:4326.
MENTENG_BBOX = (-6.2100, 106.8210, -6.1810, 106.8480)
PROJECTED_CRS = "EPSG:32748"  # WGS 84 / UTM zone 48S -- metres, correct for Jakarta
SAMPLE_SIDE_M = 2_000.0
OVERLAP_EPSILON_M2 = 1e-6

# Metre-based thresholds: the library defaults assume unit-agnostic coordinates.
REPAIR_CONFIG = RepairConfig(
    remove_duplicate_vertices=True,
    fix_invalid=True,
    remove_slivers=True,
    sliver_area_threshold=0.5,  # m2
    sliver_thinness_threshold=1e-3,
    resolve_overlaps=True,
    fill_gaps=True,
    gap_area_threshold=2.0,  # m2
)


@dataclass(frozen=True)
class Window:
    """The sampled 4 km2 study window in both geographic and projected CRS."""

    south: float
    west: float
    north: float
    east: float
    projected: Polygon

    def as_dict(self) -> dict[str, float]:
        return {"south": self.south, "west": self.west, "north": self.north, "east": self.east}


def draw_window(seed: int) -> Window:
    """Pick a random 2 km x 2 km window whose centre falls inside Menteng."""
    rng = random.Random(seed)
    to_utm = Transformer.from_crs("EPSG:4326", PROJECTED_CRS, always_xy=True)
    to_wgs84 = Transformer.from_crs(PROJECTED_CRS, "EPSG:4326", always_xy=True)
    south, west, north, east = MENTENG_BBOX
    centre_x, centre_y = to_utm.transform(rng.uniform(west, east), rng.uniform(south, north))
    half = SAMPLE_SIDE_M / 2
    min_lon, min_lat = to_wgs84.transform(centre_x - half, centre_y - half)
    max_lon, max_lat = to_wgs84.transform(centre_x + half, centre_y + half)
    return Window(
        south=min_lat,
        west=min_lon,
        north=max_lat,
        east=max_lon,
        projected=box(centre_x - half, centre_y - half, centre_x + half, centre_y + half),
    )


def fetch_buildings(window: Window, cache: Path) -> dict[str, Any]:
    """Download building ways from Overpass, reusing a cached response if present."""
    if cache.exists():
        return dict(json.loads(cache.read_text(encoding="utf-8")))
    query = (
        f"[out:json][timeout:90];"
        f'way["building"]({window.south},{window.west},{window.north},{window.east});'
        f"out geom;"
    )
    payload = urllib.parse.urlencode({"data": query}).encode()
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            request = urllib.request.Request(
                endpoint,
                data=payload,
                headers={"User-Agent": "GeoQC-osm-field-test/0.1 (evaluation)"},
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                raw = json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            print(f"  overpass endpoint failed ({endpoint}): {error}")
            time.sleep(3)
            continue
        cache.write_text(json.dumps(raw), encoding="utf-8")
        return dict(raw)
    raise RuntimeError("All Overpass endpoints failed; refusing to continue without real data.")


def to_frame(raw: dict[str, Any], window: Window) -> tuple[gpd.GeoDataFrame, dict[str, int]]:
    """Convert the Overpass payload into a projected GeoDataFrame of closed ways."""
    rows: list[dict[str, Any]] = []
    skipped = {"open_way": 0, "too_few_nodes": 0, "not_a_way": 0}
    for element in raw.get("elements", []):
        if element.get("type") != "way":
            skipped["not_a_way"] += 1
            continue
        coordinates = [(node["lon"], node["lat"]) for node in element.get("geometry") or []]
        if len(coordinates) < 4:
            skipped["too_few_nodes"] += 1
            continue
        if coordinates[0] != coordinates[-1]:
            skipped["open_way"] += 1
            continue
        tags = element.get("tags", {})
        rows.append(
            {
                "osm_id": int(element["id"]),
                "building": str(tags.get("building", "yes"))[:32],
                "name": str(tags.get("name", ""))[:64],
                "geometry": Polygon(coordinates),
            }
        )
    frame = gpd.GeoDataFrame(rows, crs="EPSG:4326").to_crs(PROJECTED_CRS)
    frame = frame[frame.geometry.intersects(window.projected)].reset_index(drop=True)
    return frame, skipped


def overlap_pairs(geometries: list[BaseGeometry]) -> list[tuple[int, int, float, BaseGeometry]]:
    """Find every pair of features sharing more than a numerical-noise area."""
    tree = STRtree(geometries)
    pairs: list[tuple[int, int, float, BaseGeometry]] = []
    for left, geometry in enumerate(geometries):
        for candidate in tree.query(geometry):
            right = int(candidate)
            if right <= left:
                continue
            shared = geometry.intersection(geometries[right])
            if not shared.is_empty and shared.area > OVERLAP_EPSILON_M2:
                pairs.append((left, right, float(shared.area), shared))
    return pairs


def audit(geometries: list[BaseGeometry], label: str) -> dict[str, Any]:
    """Run the GeoQC quality checks that do not modify anything."""
    print(f"  auditing {label} ...")
    validations = [validate_geometry(geometry) for geometry in geometries]
    invalid = [index for index, item in enumerate(validations) if not item.is_valid]
    issue_counts: dict[str, int] = {}
    for index in invalid:
        for issue in validations[index].issues:
            key = str(issue.issue_type.value)
            issue_counts[key] = issue_counts.get(key, 0) + 1
    pairs = overlap_pairs(geometries)
    small = analyze_small_polygons(geometries, SmallPolygonConfig())
    duplicates = detect_spatial_duplicates(geometries)
    return {
        "feature_count": len(geometries),
        "invalid_features": len(invalid),
        "invalid_issue_counts": issue_counts,
        "overlapping_pairs": len(pairs),
        "overlapping_area_m2": round(sum(pair[2] for pair in pairs), 3),
        "features_in_overlap": len({index for pair in pairs for index in pair[:2]}),
        "small_polygon_findings": len(small.findings),
        "duplicate_pairs": len(duplicates.pairs),
        "total_area_m2": round(sum(geometry.area for geometry in geometries), 3),
    }


def zoom_extent(pairs: list[tuple[int, int, float, BaseGeometry]], side: float = 160.0) -> Polygon:
    """Square window centred on the single worst overlap, for the map inset."""
    worst = max(pairs, key=lambda pair: pair[2])
    centre_x, centre_y = worst[3].centroid.x, worst[3].centroid.y
    half = side / 2
    return box(centre_x - half, centre_y - half, centre_x + half, centre_y + half)


def draw_map(
    frame: gpd.GeoDataFrame,
    defects: gpd.GeoSeries,
    window: Polygon,
    inset: Polygon,
    path: Path,
    title: str,
    subtitle: str,
    accent: str,
) -> None:
    """Render one full-window map with a zoomed inset on the worst defect cluster."""
    figure, axis = plt.subplots(figsize=(9.5, 10.0), dpi=170)
    frame.plot(ax=axis, facecolor="#d6dbe3", edgecolor="#7c8798", linewidth=0.18)
    highlight = frame.loc[frame["flagged"]]
    if not highlight.empty:
        highlight.plot(ax=axis, facecolor=accent, edgecolor="#111827", linewidth=0.5, alpha=0.85)
    if not defects.empty:
        gpd.GeoSeries(defects, crs=frame.crs).plot(
            ax=axis, facecolor="#b91c1c", edgecolor="#7f1d1d", linewidth=0.6, hatch="///"
        )

    min_x, min_y, max_x, max_y = window.bounds
    axis.set_xlim(min_x, max_x)
    axis.set_ylim(min_y, max_y)
    axis.set_aspect("equal")
    axis.set_title(title, fontsize=15, fontweight="bold", pad=14)
    axis.set_xlabel(f"Easting (m) — {PROJECTED_CRS}", fontsize=9)
    axis.set_ylabel(f"Northing (m) — {PROJECTED_CRS}", fontsize=9)
    axis.tick_params(labelsize=7)
    axis.grid(alpha=0.18, linewidth=0.4)
    axis.text(
        0.5,
        -0.085,
        subtitle,
        transform=axis.transAxes,
        ha="center",
        fontsize=10,
        color="#334155",
    )

    zoom_x0, zoom_y0, zoom_x1, zoom_y1 = inset.bounds
    axis.add_patch(
        Rectangle(
            (zoom_x0, zoom_y0),
            zoom_x1 - zoom_x0,
            zoom_y1 - zoom_y0,
            fill=False,
            edgecolor="#1d4ed8",
            linewidth=1.6,
            linestyle="--",
        )
    )

    lens = axis.inset_axes((0.605, 0.675, 0.385, 0.305))
    clipped = frame[frame.geometry.intersects(inset)]
    clipped.plot(ax=lens, facecolor="#d6dbe3", edgecolor="#5b6675", linewidth=0.6)
    clipped_highlight = clipped.loc[clipped["flagged"]]
    if not clipped_highlight.empty:
        clipped_highlight.plot(
            ax=lens, facecolor=accent, edgecolor="#111827", linewidth=1.0, alpha=0.9
        )
    inset_defects = [shape for shape in defects if shape.intersects(inset)]
    if inset_defects:
        gpd.GeoSeries(inset_defects, crs=frame.crs).plot(
            ax=lens, facecolor="#b91c1c", edgecolor="#7f1d1d", linewidth=0.8, hatch="///"
        )
    lens.set_xlim(zoom_x0, zoom_x1)
    lens.set_ylim(zoom_y0, zoom_y1)
    lens.set_aspect("equal")
    lens.set_xticks([])
    lens.set_yticks([])
    for spine in lens.spines.values():
        spine.set_edgecolor("#1d4ed8")
        spine.set_linewidth(1.6)
    lens.set_title("worst overlap cluster (160 m)", fontsize=8, color="#1d4ed8", pad=4)

    legend = [
        Line2D([], [], marker="s", linestyle="", markerfacecolor="#d6dbe3",
               markeredgecolor="#7c8798", markersize=9, label="OSM building (untouched)"),
        Line2D([], [], marker="s", linestyle="", markerfacecolor=accent,
               markeredgecolor="#111827", markersize=9, label="feature involved in a defect"),
        Line2D([], [], marker="s", linestyle="", markerfacecolor="#b91c1c",
               markeredgecolor="#7f1d1d", markersize=9, label="overlapping area"),
    ]
    axis.legend(handles=legend, loc="lower left", fontsize=8, framealpha=0.92)
    figure.savefig(path, format="jpg", bbox_inches="tight", pil_kwargs={"quality": 92})
    plt.close(figure)
    print(f"  wrote {path.name}")


def run(seed: int, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    window = draw_window(seed)
    print(f"window (seed={seed}): {window.as_dict()}")

    raw = fetch_buildings(window, output_dir / "overpass_response.json")
    frame, skipped = to_frame(raw, window)
    print(f"  {len(frame)} building polygons kept, skipped={skipped}")

    before_geometries = list(frame.geometry)
    before_audit = audit(before_geometries, "BEFORE")
    print(f"  BEFORE: {json.dumps(before_audit)}")

    print("  running GeoQC coverage repair ...")
    started = time.perf_counter()
    session = RepairSession(
        [shapely.to_wkt(geometry) for geometry in before_geometries],
        ShapelyTopologyRepairer(),
        REPAIR_CONFIG,
    )
    result = session.apply()
    elapsed = time.perf_counter() - started
    after_geometries = [shapely.from_wkt(wkt) for wkt in result.after_wkt]
    print(f"  repair finished in {elapsed:.1f}s")

    after_audit = audit(after_geometries, "AFTER")
    print(f"  AFTER: {json.dumps(after_audit)}")

    before_pairs = overlap_pairs(before_geometries)
    after_pairs = overlap_pairs(after_geometries)
    flagged = {index for pair in before_pairs for index in pair[:2]}
    flagged |= {
        item.feature_index for item in result.report.results if item.result.is_changed
    }

    attributes = [
        {
            "osm_id": frame.at[index, "osm_id"],
            "building": frame.at[index, "building"],
            "name": frame.at[index, "name"],
            "flagged": index in flagged,
            "valid": bool(before_geometries[index].is_valid),
            "area_m2": round(before_geometries[index].area, 3),
            "status": "original",
            "actions": "",
        }
        for index in range(len(frame))
    ]
    before_frame = gpd.GeoDataFrame(attributes, geometry=before_geometries, crs=PROJECTED_CRS)

    after_attributes = []
    for index, item in enumerate(result.report.results):
        actions = ";".join(sorted({action.issue_type.value for action in item.result.actions}))
        after_attributes.append(
            {
                **attributes[index],
                "valid": bool(after_geometries[index].is_valid),
                "area_m2": round(after_geometries[index].area, 3),
                "status": str(item.result.status.value),
                "actions": actions[:100],
                "shift_m": round(item.result.metrics.shape_shift, 4),
                "d_area_m2": round(item.result.metrics.area_delta, 3),
                "fail_why": str(item.result.failure_reason or "")[:100],
            }
        )
    after_frame = gpd.GeoDataFrame(after_attributes, geometry=after_geometries, crs=PROJECTED_CRS)

    failure_reasons: dict[str, int] = {}
    for item in result.report.results:
        if item.result.failure_reason:
            key = item.result.failure_reason
            failure_reasons[key] = failure_reasons.get(key, 0) + 1

    before_frame.to_file(output_dir / "menteng_osm_before.shp", driver="ESRI Shapefile")
    after_frame.to_file(output_dir / "menteng_osm_after.shp", driver="ESRI Shapefile")
    print("  wrote before/after Shapefiles")

    inset = zoom_extent(before_pairs) if before_pairs else window.projected
    draw_map(
        before_frame,
        gpd.GeoSeries([pair[3] for pair in before_pairs], crs=PROJECTED_CRS),
        window.projected,
        inset,
        output_dir / "menteng_osm_before.jpg",
        "BEFORE — raw OpenStreetMap buildings, Menteng 4 km²",
        f"{before_audit['feature_count']} buildings · "
        f"{before_audit['overlapping_pairs']} overlapping pairs · "
        f"{before_audit['overlapping_area_m2']:,.0f} m² double-counted · "
        f"{before_audit['small_polygon_findings']} sliver findings",
        "#f97316",
    )
    draw_map(
        after_frame,
        gpd.GeoSeries([pair[3] for pair in after_pairs], crs=PROJECTED_CRS),
        window.projected,
        inset,
        output_dir / "menteng_osm_after.jpg",
        "AFTER — repaired with GeoQC coverage repair",
        f"{after_audit['feature_count']} buildings · "
        f"{after_audit['overlapping_pairs']} overlapping pairs · "
        f"{after_audit['overlapping_area_m2']:,.0f} m² double-counted · "
        f"{result.report.repaired_count} features changed in {elapsed:.1f}s",
        "#16a34a",
    )

    report = {
        "source": {
            "provider": "OpenStreetMap via Overpass API",
            "licence": "ODbL 1.0 (c) OpenStreetMap contributors",
            "area": "Menteng, Jakarta Pusat, Indonesia",
            "sample_km2": (SAMPLE_SIDE_M / 1000) ** 2,
            "window_wgs84": window.as_dict(),
            "projected_crs": PROJECTED_CRS,
            "seed": seed,
            "defects": "genuine, present in the OSM database; nothing injected or mocked",
        },
        "before": before_audit,
        "after": after_audit,
        "repair": {
            "config": {
                key: getattr(REPAIR_CONFIG, key) for key in REPAIR_CONFIG.__dataclass_fields__
            },
            "elapsed_seconds": round(elapsed, 2),
            "total": result.report.total,
            "repaired": result.report.repaired_count,
            "unchanged": result.report.unchanged_count,
            "failed": result.report.failed_count,
            "action_counts": result.report.action_counts,
            "total_area_delta_m2": round(result.report.total_area_delta, 3),
            "max_shape_shift_m": round(result.report.max_shape_shift, 4),
            "undo_available": session.can_undo,
            "failure_reasons": failure_reasons,
            "failed_features": [
                {
                    "feature_index": item.feature_index,
                    "osm_id": int(frame.at[item.feature_index, "osm_id"]),
                    "reason": item.result.failure_reason,
                }
                for item in result.report.results
                if item.result.status.value == "failed"
            ][:25],
        },
        "delta": {
            "overlapping_pairs": after_audit["overlapping_pairs"]
            - before_audit["overlapping_pairs"],
            "overlapping_area_m2": round(
                after_audit["overlapping_area_m2"] - before_audit["overlapping_area_m2"], 3
            ),
            "total_area_m2": round(
                after_audit["total_area_m2"] - before_audit["total_area_m2"], 3
            ),
        },
        "outputs": sorted(path.name for path in output_dir.iterdir()),
    }
    (output_dir / "menteng_qc_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260726)
    parser.add_argument("--output", type=Path, default=Path("artifacts/menteng_osm_qc"))
    arguments = parser.parse_args()
    report = run(arguments.seed, arguments.output)
    print(json.dumps({k: v for k, v in report.items() if k != "outputs"}, indent=2))


if __name__ == "__main__":
    main()
