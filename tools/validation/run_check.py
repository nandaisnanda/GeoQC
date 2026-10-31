"""Audit every dataset in data/ and sample findings per rule code for manual review."""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import pandas as pd
from pyogrio import list_layers, read_info, write_dataframe

from geoqc.infrastructure.gis.dataset_audit import audit_dataset
from geoqc.infrastructure.gis.profile_loading import _generic_profile

SUFFIXES = {".shp", ".gpkg", ".geojson", ".fgb", ".parquet"}
COLUMNS = ["dataset", "layer", "code", "feature_index", "message", "verdict", "note"]
HERE = Path(__file__).parent


def collect(data: Path, per_code: int, seed: int) -> pd.DataFrame:
    rng = random.Random(seed)
    pool: dict[str, list[dict[str, object]]] = {}
    for path in sorted(p for p in data.rglob("*") if p.suffix.lower() in SUFFIXES):
        for name, geometry_type in list_layers(path):
            if geometry_type is None:
                continue
            layer = str(name)
            info = read_info(path, layer=layer)
            profile = _generic_profile(info.get("geometry_type"))
            result = audit_dataset(path, layer=layer, profile=profile)
            for issue in result.issues:
                index = issue.feature_index
                pool.setdefault(issue.code, []).append(
                    {
                        "dataset": path.name,
                        "layer": layer,
                        "code": issue.code,
                        "feature_index": -1 if index is None else index,
                        "message": issue.message,
                        "verdict": "",
                        "note": "",
                    }
                )
    rows: list[dict[str, object]] = []
    for code in sorted(pool):
        items = pool[code]
        rows.extend(rng.sample(items, min(per_code, len(items))))
    return pd.DataFrame(rows, columns=COLUMNS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=HERE / "data")
    parser.add_argument("--out", type=Path, default=HERE / "out" / "review.gpkg")
    parser.add_argument("--per-code", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    frame = collect(args.data, args.per_code, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_dataframe(frame, args.out, layer="review", driver="GPKG")
    print(f"{len(frame)} findings sampled from {frame['dataset'].nunique()} datasets -> {args.out}")


if __name__ == "__main__":
    main()
