# GeoQC Web

React + TypeScript client for local geometry validation and intelligent
topology-repair previews. The client uploads an allowlisted vector dataset to
the same-origin FastAPI service and displays validation findings or a repair
report.

## Development

Run the API from the repository root:

```bash
python -m uvicorn geoqc.interfaces.api.main:app --host 127.0.0.1 --port 8000
```

Then run the Vite client:

```bash
cd apps/web
npm install
npm run dev
```

Vite proxies `/api` to the local backend. Supported uploads are GeoJSON,
GeoPackage, FlatGeobuf, or a complete Shapefile component set.

## Repair workflow

- **Preview repair** calls `POST /api/geometry/repair`; the server does not
  overwrite the uploaded dataset.
- **Apply preview** marks the returned repaired snapshot as the active result
  and enables **Download repaired GeoJSON**.
- **Undo** returns to the original snapshot by clearing that local selection.
- **Download report** exports counts, actions, metrics, and before/after WKT.

The production Python API also offers a multi-level snapshot Undo Engine through
`open_repair_session`. See
[`docs/topology-repair.md`](../../docs/topology-repair.md) for strategies,
thresholds, safety guarantees, and limitations.

## Quality checks

```bash
npm run lint
npm test
npm run build
```
