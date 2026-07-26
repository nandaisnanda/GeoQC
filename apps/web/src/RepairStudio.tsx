import { useMemo, useState } from "react";
import type { JSX } from "react";

export type StudioFeature = {
  feature_index: number;
  before_wkt: string;
  after_wkt: string;
  actions: { issue_type: string; strategy: string; detail: string }[];
};

type Decision = "pending" | "approved" | "rejected";
type HistoryEntry = { feature: number; from: Decision; to: Decision; at: string };

export function RepairStudio({ features }: { features: StudioFeature[] }): JSX.Element {
  const [selected, setSelected] = useState(0);
  const [decisions, setDecisions] = useState<Record<number, Decision>>({});
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const feature = features[selected];
  const counts = useMemo(() => ({
    approved: Object.values(decisions).filter((value) => value === "approved").length,
    rejected: Object.values(decisions).filter((value) => value === "rejected").length,
  }), [decisions]);

  function decide(to: Decision): void {
    if (!feature) return;
    const from = decisions[feature.feature_index] ?? "pending";
    if (from === to) return;
    setDecisions({ ...decisions, [feature.feature_index]: to });
    setHistory([...history, { feature: feature.feature_index, from, to, at: new Date().toISOString() }]);
  }

  function undo(): void {
    const entry = history.at(-1);
    if (!entry) return;
    setDecisions({ ...decisions, [entry.feature]: entry.from });
    setHistory(history.slice(0, -1));
  }

  if (!feature) return <p className="empty-state">No changed geometry is available.</p>;
  const decision = decisions[feature.feature_index] ?? "pending";
  return (
    <section className="repair-studio" aria-label="Interactive Repair Studio">
      <div className="studio-toolbar">
        <div><span className="eyebrow">Interactive Repair Studio</span><h3>Compare geometry</h3></div>
        <div className="studio-counts"><span>{counts.approved} approved</span><span>{counts.rejected} rejected</span></div>
      </div>
      <div className="studio-layout">
        <aside className="studio-list" aria-label="Changed features">
          {features.map((item, index) => (
            <button className={index === selected ? "is-selected" : ""} type="button" key={item.feature_index} onClick={() => setSelected(index)}>
              <span>Feature #{item.feature_index}</span><small>{decisions[item.feature_index] ?? "pending"}</small>
            </button>
          ))}
        </aside>
        <div className="studio-workspace">
          <div className="geometry-compare">
            <GeometryCard title="Before" wkt={feature.before_wkt} tone="before" />
            <GeometryCard title="After" wkt={feature.after_wkt} tone="after" />
          </div>
          <div className="studio-actions">
            <span className={`decision decision-${decision}`}>{decision}</span>
            <button type="button" className="btn btn-primary btn-sm" onClick={() => decide("approved")}>Approve repair</button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => decide("rejected")}>Reject repair</button>
            <button type="button" className="btn btn-ghost btn-sm" disabled={history.length === 0} onClick={undo}>Undo</button>
          </div>
        </div>
      </div>
      <details className="studio-history"><summary>History · {history.length} event{history.length === 1 ? "" : "s"}</summary>
        <ol>{[...history].reverse().map((entry, index) => <li key={`${entry.at}-${index}`}>Feature #{entry.feature}: {entry.from} → {entry.to}</li>)}</ol>
      </details>
    </section>
  );
}

function GeometryCard({ title, wkt, tone }: { title: string; wkt: string; tone: string }): JSX.Element {
  return <article className={`geometry-card geometry-${tone}`}><header><strong>{title}</strong></header><div className="geometry-canvas"><span>{wkt.slice(0, 140)}{wkt.length > 140 ? "…" : ""}</span></div><code>{wkt}</code></article>;
}