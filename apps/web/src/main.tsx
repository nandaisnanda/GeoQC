import { StrictMode, useEffect, useMemo, useRef, useState } from "react";
import type { DragEvent, JSX, ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { RepairStudio } from "./RepairStudio";
import "./styles.css";

type GeometryIssue = { type: string; message: string };
type Finding = { feature_index: number; issues: GeometryIssue[] };
type ValidationResult = {
  filename: string;
  layer: string | null;
  feature_count: number;
  valid_feature_count: number;
  invalid_feature_count: number;
  issue_counts: Record<string, number>;
  findings: Finding[];
  findings_truncated: boolean;
};

type RepairAction = { issue_type: string; strategy: string; detail: string };
type RepairFeature = {
  feature_index: number;
  status: string;
  geometry_type: string;
  actions: RepairAction[];
  area_before: number;
  area_after: number;
  shape_shift: number;
  before_wkt: string;
  after_wkt: string;
};
type RepairResult = {
  filename: string;
  layer: string | null;
  mode: "preview";
  total: number;
  repaired: number;
  unchanged: number;
  failed: number;
  action_counts: Record<string, number>;
  total_area_delta: number;
  max_shape_shift: number;
  findings: RepairFeature[];
  findings_truncated: boolean;
  original_geojson: string;
  repaired_geojson: string;
};

const requiredExtensions = [".shp", ".shx", ".dbf"];
const shapefileExtensions = [".shp", ".shx", ".dbf", ".prj", ".cpg"];
const singleFileExtensions = new Set([".geojson", ".json", ".gpkg", ".fgb", ".parquet"]);
const acceptAttribute = [...shapefileExtensions, ...singleFileExtensions].join(",");
const maximumUploadBytes = 100 * 1024 * 1024;
const requestTimeoutMs = 120_000;

const issueLabels: Record<string, string> = {
  invalid_geometry: "Invalid geometry",
  empty_geometry: "Empty geometry",
  self_intersection: "Self-intersection",
  ring_error: "Ring error",
  duplicate_vertex: "Duplicate vertex",
};

const repairLabels: Record<string, string> = {
  self_intersection: "Self-intersection",
  invalid_ring: "Invalid ring",
  duplicate_vertex: "Duplicate vertex",
  sliver_polygon: "Sliver polygon",
  overlap: "Overlap",
  gap: "Gap",
};

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot < 0 ? "" : filename.slice(dot).toLowerCase();
}

function formatBytes(total: number): string {
  if (total < 1024) return `${total} B`;
  const units = ["KB", "MB", "GB"];
  let value = total / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`;
}

async function fileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const chunkSize = 0x8000;
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return window.btoa(binary);
}

function isValidationResult(value: unknown): value is ValidationResult {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.filename === "string"
    && (typeof candidate.layer === "string" || candidate.layer === null)
    && typeof candidate.feature_count === "number"
    && typeof candidate.valid_feature_count === "number"
    && typeof candidate.invalid_feature_count === "number"
    && typeof candidate.issue_counts === "object"
    && Array.isArray(candidate.findings)
    && typeof candidate.findings_truncated === "boolean";
}

function isRepairResult(value: unknown): value is RepairResult {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.filename === "string"
    && typeof candidate.total === "number"
    && typeof candidate.repaired === "number"
    && typeof candidate.action_counts === "object"
    && Array.isArray(candidate.findings)
    && candidate.mode === "preview"
    && typeof candidate.original_geojson === "string"
    && typeof candidate.repaired_geojson === "string";
}

function downloadGeoJSON(result: RepairResult): void {
  const blob = new Blob([result.repaired_geojson], { type: "application/geo+json" });
  const url = URL.createObjectURL(blob);
  const base = result.filename.replace(/\.[^.]+$/, "") || "geoqc-repaired";
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${base}.repaired.geojson`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function downloadRepairReport(result: RepairResult): void {
  const report: Omit<RepairResult, "original_geojson" | "repaired_geojson"> = {
    filename: result.filename,
    layer: result.layer,
    mode: result.mode,
    total: result.total,
    repaired: result.repaired,
    unchanged: result.unchanged,
    failed: result.failed,
    action_counts: result.action_counts,
    total_area_delta: result.total_area_delta,
    max_shape_shift: result.max_shape_shift,
    findings: result.findings,
    findings_truncated: result.findings_truncated,
  };
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const base = result.filename.replace(/\.[^.]+$/, "") || "geoqc-repair";
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${base}.repair-report.json`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function errorMessage(caught: unknown, action: string): string {
  if (caught instanceof DOMException && caught.name === "AbortError") {
    return `${action} timed out. Try a smaller dataset.`;
  }
  return caught instanceof Error ? caught.message : `${action} failed.`;
}

type SelectionState = { ok: boolean; message: string };

function evaluateSelection(files: File[]): SelectionState {
  if (files.length === 0) return { ok: false, message: "" };

  const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
  if (totalBytes > maximumUploadBytes) {
    return { ok: false, message: "The selected files exceed the 100 MiB limit." };
  }

  const extensions = files.map((file) => extensionOf(file.name));
  const isSingleFile = files.length === 1 && singleFileExtensions.has(extensions[0]);
  if (isSingleFile) return { ok: true, message: "" };

  const unsupported = extensions.filter((extension) => !shapefileExtensions.includes(extension));
  if (files.length === 1 || unsupported.length > 0) {
    return {
      ok: false,
      message: "Select one dataset file, or a complete Shapefile component set (.shp, .shx, .dbf).",
    };
  }

  const present = new Set(extensions);
  const missing = requiredExtensions.filter((extension) => !present.has(extension));
  if (missing.length > 0) {
    return { ok: false, message: `Missing Shapefile component${missing.length > 1 ? "s" : ""}: ${missing.join(", ")}.` };
  }
  return { ok: true, message: "" };
}

type Theme = "light" | "dark";

function initialTheme(): Theme {
  const stored = window.localStorage.getItem("geoqc-theme");
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function Icon({ path, size = 20 }: { path: ReactNode; size?: number }): JSX.Element {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {path}
    </svg>
  );
}

function App(): JSX.Element {
  const [files, setFiles] = useState<File[]>([]);
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [repairResult, setRepairResult] = useState<RepairResult | null>(null);
  const [appliedRepair, setAppliedRepair] = useState<RepairResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"" | "validate" | "repair">("");
  const [layer, setLayer] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("geoqc-theme", theme);
  }, [theme]);

  const selection = useMemo(() => evaluateSelection(files), [files]);
  const isGeoPackage = files.length === 1 && extensionOf(files[0].name) === ".gpkg";
  const loading = busy !== "";

  function selectFiles(next: File[]): void {
    setFiles(next);
    setResult(null);
    setRepairResult(null);
    setAppliedRepair(null);
    setError("");
    setLayer("");
  }

  function onDrop(event: DragEvent<HTMLElement>): void {
    event.preventDefault();
    setDragActive(false);
    const dropped = Array.from(event.dataTransfer.files);
    if (dropped.length > 0) selectFiles(dropped);
  }

  function removeFile(index: number): void {
    selectFiles(files.filter((_, position) => position !== index));
  }

  function reset(): void {
    selectFiles([]);
    if (inputRef.current) inputRef.current.value = "";
  }

  async function request(
    path: string,
    action: "validate" | "repair",
    extra: Record<string, unknown> = {},
  ): Promise<unknown> {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), requestTimeoutMs);
    try {
      const payload = await Promise.all(
        files.map(async (file) => ({
          name: file.name,
          content_base64: await fileToBase64(file),
        })),
      );
      const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ files: payload, ...(layer.trim() && { layer: layer.trim() }), ...extra }),
        signal: controller.signal,
      });
      const contentType = response.headers.get("content-type") ?? "";
      const body: unknown = contentType.includes("application/json") ? await response.json() : null;
      if (!response.ok) {
        const detail =
          typeof body === "object" && body !== null && "detail" in body
            ? String(body.detail)
            : `${action === "repair" ? "Repair" : "Validation"} failed with HTTP ${response.status}.`;
        throw new Error(detail);
      }
      return body;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function validate(): Promise<void> {
    setBusy("validate");
    setError("");
    setResult(null);
    setRepairResult(null);
    setAppliedRepair(null);
    try {
      const body = await request("/api/geometry/validate", "validate");
      if (!isValidationResult(body)) {
        throw new Error("The server returned an unexpected response.");
      }
      setResult(body);
    } catch (caught) {
      setError(errorMessage(caught, "Validation"));
    } finally {
      setBusy("");
    }
  }

  async function repair(): Promise<void> {
    setBusy("repair");
    setError("");
    setResult(null);
    setRepairResult(null);
    try {
      const body = await request("/api/geometry/repair", "repair", { mode: "preview" });
      if (!isRepairResult(body)) {
        throw new Error("The server returned an unexpected response.");
      }
      setRepairResult(body);
      setAppliedRepair(null);
    } catch (caught) {
      setError(errorMessage(caught, "Repair"));
    } finally {
      setBusy("");
    }
  }

  const canValidate = selection.ok && !loading;

  return (
    <>
      <a className="skip-link" href="#validator">Skip to validator</a>

      <header className="topbar">
        <div className="shell topbar-inner">
          <a className="wordmark" href="#top" aria-label="GeoQC home">
            <span className="mark" aria-hidden="true">
              <Icon size={18} path={<><path d="M12 21s7-5.4 7-11a7 7 0 0 0-14 0c0 5.6 7 11 7 11Z" /><circle cx="12" cy="10" r="2.4" /></>} />
            </span>
            <span className="wordmark-text">GeoQC</span>
            <span className="version">v0.1.0</span>
          </a>
          <nav className="topnav" aria-label="Primary">
            <a href="https://github.com/GeoQC/geoqc/tree/main/docs">Docs</a>
            <a href="https://github.com/GeoQC/geoqc" className="topnav-icon" aria-label="GitHub repository">
              <Icon path={<path d="M9 19c-4.3 1.4-4.3-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.5 1.3a12 12 0 0 0-6.2 0C6.7 2.3 5.6 2.6 5.6 2.6a4.2 4.2 0 0 0-.1 3.2A4.6 4.6 0 0 0 4.2 9c0 4.6 2.7 5.7 5.5 6-.6.6-.6 1.2-.5 2V21" />} />
            </a>
            <button
              type="button"
              className="theme-toggle"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            >
              {theme === "dark"
                ? <Icon path={<><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>} />
                : <Icon path={<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />} />}
            </button>
          </nav>
        </div>
      </header>

      <main className="shell page" id="top">
        <section className="intro">
          <span className="eyebrow">In-browser validation</span>
          <h1>Geometry quality control, no install required</h1>
          <p className="lede">
            Upload a dataset and validate it with the same <code className="lede-code">geoqc</code>{" "}
            engine that powers the Python package and CLI. Processing runs server-side and
            never alters your source data.
          </p>
        </section>

        <section id="validator" className="panel" aria-labelledby="upload-heading">
          <div className="panel-head">
            <h2 id="upload-heading">Upload dataset</h2>
            <p>Shapefile, GeoJSON, GeoPackage, FlatGeobuf, or GeoParquet · 100 MiB maximum</p>
          </div>

          <label
            className={`dropzone${dragActive ? " is-active" : ""}`}
            onDragOver={(event) => { event.preventDefault(); setDragActive(true); }}
            onDragLeave={() => setDragActive(false)}
            onDrop={onDrop}
          >
            <span className="dropzone-icon" aria-hidden="true">
              <Icon size={26} path={<><path d="M12 16V4M7 9l5-5 5 5" /><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" /></>} />
            </span>
            <span className="dropzone-title">Drag a dataset here, or <span className="link-like">browse files</span></span>
            <span className="dropzone-hint">Shapefiles need their .shp, .shx, and .dbf components together</span>
            <input
              ref={inputRef}
              type="file"
              multiple
              accept={acceptAttribute}
              onChange={(event) => selectFiles(Array.from(event.target.files ?? []))}
            />
          </label>

          {files.length > 0 && (
            <ul className="file-list">
              {files.map((file, index) => (
                <li key={`${file.name}-${index}`} className="file-row">
                  <span className="file-type">{(extensionOf(file.name).slice(1) || "?").toUpperCase()}</span>
                  <span className="file-name">{file.name}</span>
                  <span className="file-size">{formatBytes(file.size)}</span>
                  <button
                    type="button"
                    className="file-remove"
                    onClick={() => removeFile(index)}
                    aria-label={`Remove ${file.name}`}
                  >
                    <Icon size={16} path={<path d="M18 6 6 18M6 6l12 12" />} />
                  </button>
                </li>
              ))}
            </ul>
          )}

          {isGeoPackage && (
            <div className="field">
              <label htmlFor="layer">GeoPackage layer</label>
              <input
                id="layer"
                type="text"
                maxLength={255}
                placeholder="Optional — required only for multi-layer files"
                value={layer}
                onChange={(event) => setLayer(event.target.value)}
              />
            </div>
          )}

          {selection.message && (
            <p className="notice notice-warn" role="alert">
              <Icon size={16} path={<><path d="M12 9v4M12 17h.01" /><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /></>} />
              {selection.message}
            </p>
          )}

          <div className="actions">
            <button type="button" className="btn btn-primary" disabled={!canValidate} onClick={validate}>
              {loading
                ? <><span className="spinner" aria-hidden="true" />Validating…</>
                : "Run validation"}
            </button>
            <button type="button" className="btn btn-ghost" disabled={!canValidate} onClick={repair}>
              {busy === "repair"
                ? <><span className="spinner" aria-hidden="true" />Previewing repair…</>
                : "Preview topology repair"}
            </button>
            {files.length > 0 && (
              <button type="button" className="btn btn-ghost" disabled={loading} onClick={reset}>
                Clear
              </button>
            )}
          </div>

          <p className="status" role="status" aria-live="polite">
            {busy === "validate" ? "Reading and validating the dataset…" : busy === "repair" ? "Computing a non-destructive repair preview…" : ""}
          </p>
          {error && (
            <p className="notice notice-error" role="alert">
              <Icon size={16} path={<><circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" /></>} />
              {error}
            </p>
          )}
        </section>

        {result && <Report result={result} />}
        {repairResult && (
          <RepairReport
            result={repairResult}
            applied={appliedRepair !== null}
            onApply={() => setAppliedRepair(repairResult)}
            onUndo={() => setAppliedRepair(null)}
          />
        )}
      </main>

      <footer className="shell site-footer">
        <p>GeoQC — a typed, open-source GIS quality-control toolkit.</p>
        <a href="https://github.com/GeoQC/geoqc/blob/main/LICENSE">MIT License</a>
      </footer>
    </>
  );
}

function downloadReport(result: ValidationResult): void {
  const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const base = result.filename.replace(/\.[^.]+$/, "") || "geoqc-report";
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${base}.geoqc.json`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function Report({ result }: { result: ValidationResult }): JSX.Element {
  const passed = result.invalid_feature_count === 0;
  const total = result.feature_count;
  const validShare = total > 0 ? (result.valid_feature_count / total) * 100 : 100;
  const activeIssues = Object.entries(issueLabels).filter(
    ([type]) => (result.issue_counts[type] ?? 0) > 0,
  );

  return (
    <section className="panel report" aria-label="Validation result">
      <div className="report-head">
        <div>
          <span className="eyebrow">Result</span>
          <h2 className="report-title">{result.filename}</h2>
          {result.layer && <p className="report-sub">Layer · {result.layer}</p>}
        </div>
        <div className="report-head-actions">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => downloadReport(result)}>
            <Icon size={15} path={<><path d="M12 3v12M8 11l4 4 4-4" /><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" /></>} />
            Download JSON
          </button>
          <span className={`verdict ${passed ? "verdict-pass" : "verdict-fail"}`}>
            <span className="verdict-dot" aria-hidden="true" />
            {passed ? "Passed" : "Needs attention"}
          </span>
        </div>
      </div>

      <div className="ratebar" role="img" aria-label={`${validShare.toFixed(1)}% of features are valid`}>
        <div className="ratebar-valid" style={{ width: `${validShare}%` }} />
        <div className="ratebar-invalid" style={{ width: `${100 - validShare}%` }} />
      </div>
      <p className="ratebar-caption">
        <strong>{validShare.toFixed(validShare % 1 === 0 ? 0 : 1)}%</strong> valid
        {total > 0 && <> · {result.valid_feature_count.toLocaleString()} of {total.toLocaleString()} features</>}
      </p>

      <div className="stats">
        <article className="stat">
          <span className="stat-label">Total features</span>
          <strong className="stat-value">{total.toLocaleString()}</strong>
        </article>
        <article className="stat stat-good">
          <span className="stat-label">Valid</span>
          <strong className="stat-value">{result.valid_feature_count.toLocaleString()}</strong>
        </article>
        <article className={`stat${result.invalid_feature_count > 0 ? " stat-bad" : ""}`}>
          <span className="stat-label">Invalid</span>
          <strong className="stat-value">{result.invalid_feature_count.toLocaleString()}</strong>
        </article>
      </div>

      {activeIssues.length > 0 && (
        <div className="issues">
          <h3>Issue breakdown</h3>
          <ul className="issue-list">
            {activeIssues.map(([type, label]) => (
              <li key={type} className="issue-item">
                <span className="issue-dot" aria-hidden="true" />
                <span className="issue-label">{label}</span>
                <span className="issue-count">{(result.issue_counts[type] ?? 0).toLocaleString()}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {result.findings.length === 0 ? (
        <p className="empty-state">
          <Icon size={18} path={<><path d="M20 6 9 17l-5-5" /></>} />
          No geometry issues were found in this dataset.
        </p>
      ) : (
        <div className="findings">
          <h3>Feature findings</h3>
          <div className="findings-list">
            {result.findings.map((finding) => (
              <details key={finding.feature_index}>
                <summary>
                  <span className="finding-index">Feature #{finding.feature_index}</span>
                  <span className="finding-count">
                    {finding.issues.length} issue{finding.issues.length > 1 ? "s" : ""}
                  </span>
                </summary>
                <ul>
                  {finding.issues.map((issue, index) => (
                    <li key={`${issue.type}-${index}`} className="issue-line">
                      <span className="issue-line-type">{issueLabels[issue.type] ?? issue.type}</span>
                      <span className="issue-line-msg">{issue.message}</span>
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </div>
          {result.findings_truncated && (
            <p className="findings-note">Detailed findings are limited to the first 1,000 affected features.</p>
          )}
        </div>
      )}
    </section>
  );
}

function RepairReport({
  result,
  applied,
  onApply,
  onUndo,
}: {
  result: RepairResult;
  applied: boolean;
  onApply: () => void;
  onUndo: () => void;
}): JSX.Element {
  const activeActions = Object.entries(result.action_counts).filter(([, count]) => count > 0);
  return (
    <section className="panel report" aria-label="Topology repair preview">
      <div className="report-head">
        <div>
          <span className="eyebrow">Repair preview</span>
          <h2 className="report-title">{result.filename}</h2>
          <p className="report-sub">
            {applied ? "Applied in this browser session — source upload remains unchanged" : "Non-destructive preview"}
          </p>
        </div>
        <div className="report-head-actions">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => downloadRepairReport(result)}>
            Download report
          </button>
          {!applied ? (
            <button type="button" className="btn btn-primary btn-sm" onClick={onApply} disabled={result.repaired === 0}>
              Apply preview
            </button>
          ) : (
            <button type="button" className="btn btn-ghost btn-sm" onClick={onUndo}>
              Undo
            </button>
          )}
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => downloadGeoJSON(result)} disabled={!applied}>
            Download repaired GeoJSON
          </button>
        </div>
      </div>

      <div className="stats repair-stats">
        <article className="stat"><span className="stat-label">Features</span><strong className="stat-value">{result.total.toLocaleString()}</strong></article>
        <article className="stat"><span className="stat-label">Repaired</span><strong className="stat-value">{result.repaired.toLocaleString()}</strong></article>
        <article className={`stat${result.failed > 0 ? " stat-bad" : ""}`}><span className="stat-label">Failed</span><strong className="stat-value">{result.failed.toLocaleString()}</strong></article>
      </div>
      <p className="repair-metrics">
        Total area delta <strong>{result.total_area_delta.toPrecision(6)}</strong> · maximum shape shift <strong>{result.max_shape_shift.toPrecision(6)}</strong>
      </p>

      {activeActions.length > 0 && (
        <div className="issues">
          <h3>Repair action breakdown</h3>
          <ul className="issue-list">
            {activeActions.map(([type, count]) => (
              <li key={type} className="issue-item">
                <span className="issue-dot repair-dot" aria-hidden="true" />
                <span className="issue-label">{repairLabels[type] ?? type}</span>
                <span className="issue-count">{count.toLocaleString()}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {result.findings.length === 0 ? (
        <p className="empty-state">No safe topology changes were proposed.</p>
      ) : (
        <>
        <RepairStudio features={result.findings} />
        <div className="findings">
          <h3>Changed features</h3>
          <div className="findings-list">
            {result.findings.map((finding) => (
              <details key={finding.feature_index}>
                <summary>
                  <span className="finding-index">Feature #{finding.feature_index}</span>
                  <span className="finding-count">{finding.actions.length} action{finding.actions.length === 1 ? "" : "s"}</span>
                </summary>
                <ul>
                  {finding.actions.map((action, index) => (
                    <li key={`${action.issue_type}-${index}`} className="issue-line repair-line">
                      <span className="issue-line-type">{repairLabels[action.issue_type] ?? action.issue_type} · {action.strategy}</span>
                      <span className="issue-line-msg">{action.detail}</span>
                    </li>
                  ))}
                  <li className="geometry-snapshot">
                    <strong>Before</strong><code>{finding.before_wkt}</code>
                    <strong>After</strong><code>{finding.after_wkt}</code>
                  </li>
                </ul>
              </details>
            ))}
          </div>
          {result.findings_truncated && <p className="findings-note">Detailed repairs are limited to the first 1,000 changed features.</p>}
        </div>
        </>
      )}
    </section>
  );
}

const rootElement: HTMLElement | null = document.getElementById("root");

if (rootElement === null) {
  throw new Error("GeoQC root element was not found.");
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
