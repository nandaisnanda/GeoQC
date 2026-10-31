# Real-data validation

Measure how many findings are real problems, per rule code.

1. Put datasets (`.shp`, `.gpkg`, `.geojson`, `.fgb`, `.parquet`) in `data/`. It is gitignored.
2. `uv run python tools/validation/run_check.py` audits every spatial layer with the generic
   preset and samples up to 50 findings per rule code (seed 42) into `out/review.gpkg`.
3. Open `out/review.gpkg` (table `review`) in QGIS. Fill `verdict`: `1` real problem,
   `0` false alarm. Use `note` for anything odd. Leave unreviewed rows empty.
4. `uv run python tools/validation/score.py` prints precision per code as a markdown table.

Options: `--data`, `--out`, `--per-code`, `--seed`. Keep the verdicts; they are future
training data.
