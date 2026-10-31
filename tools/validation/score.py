"""Print precision per rule code from a labelled review.gpkg (verdict 1 = real, 0 = false)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from pyogrio import read_dataframe

DEFAULT = Path(__file__).parent / "out" / "review.gpkg"


def precision_table(frame: pd.DataFrame) -> str:
    verdict = pd.to_numeric(frame["verdict"], errors="coerce")
    labelled = frame.assign(verdict=verdict).dropna(subset=["verdict"])
    lines = ["| code | labelled | real | precision |", "| --- | ---: | ---: | ---: |"]
    for code, group in labelled.groupby("code"):
        real = int((group["verdict"] == 1).sum())
        lines.append(f"| {code} | {len(group)} | {real} | {real / len(group):.2f} |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review", type=Path, nargs="?", default=DEFAULT)
    args = parser.parse_args()
    print(precision_table(read_dataframe(args.review, layer="review")))


if __name__ == "__main__":
    main()
