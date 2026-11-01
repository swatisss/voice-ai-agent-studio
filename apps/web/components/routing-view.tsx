// Spec: /ui/evaluation.md (Routing view), /architecture/capability-catalog.md (Routing suite), /architecture/agent-transfer.md (Misroutes)
"use client";

import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, EmptyState, Field, Input, Modal, Select, Spinner, Stat } from "@/components/ui";
import { api, ApiError, useApi, useEvents } from "@/lib/api";
import { pct, when } from "@/lib/format";

type Case = { id: string; utterance: string; expected_agent_id: string; expected_agent_name: string | null; scope: string; source: "generated" | "manual"; enabled: boolean };
type RunSummary = {
  cases: number; passed: number; accuracy: number | null; pass_mark: number; passes: boolean; confusion: Record<string, Record<string, number>>;
  by_method: Record<string, number>; latency_ms: { p50: number | null; p95: number | null }; fallbacks: number;
};
type Run = { id: string; trigger: string; status: string; summary: Partial<RunSummary>; created_at: string; finished_at: string | null };
type RunDetail = Run & { results: { case_id: string; utterance: string; expected_agent_name: string | null; chosen_agent_name: string | null; method: string; confidence: number | null; passed: boolean }[]; agent_names: Record<string, string> };
type RoutingSummary = {
  decisions: number; by_method: Record<string, number>; stage_b_rate: number | null; fallback_rate: number | null; clarification_rate: number | null;
  misroute_rate: number | null; transfers_per_conversation: number | null; decision_ms: { p50: number | null; p95: number | null };
  by_agent: { agent_id: string; agent_name: string; routed_to: number; early_transfers: number; in_scope_failures: number }[];
};

const TRIGGER: Record<string, string> = { catalog: "Catalog change", target: "Target change", manual: "Manual" };

function Confusion({ detail }: { detail: RunDetail }) {
  const conf = detail.summary.confusion ?? {};
  const expected = Object.keys(conf);
  const chosen = Array.from(new Set(expected.flatMap((e) => Object.keys(conf[e]))));
  const name = (id: string) => (id === "none" ? "None" : detail.agent_names[id] ?? id);
  return (
    <div className="overflow-x-auto">
      <table className="text-sm">
        <thead><tr><th className="p-2 text-left text-muted">Expected ↓ / Chosen →</th>{chosen.map((c) => <th key={c} className="p-2 text-left">{name(c)}</th>)}</tr></thead>
        <tbody>
          {expected.map((e) => (
            <tr key={e} className="border-t border-[var(--border)]">
              <th className="p-2 text-left">{name(e)}</th>
              {chosen.map((c) => {
                const n = conf[e][c] ?? 0;
                return <td key={c} className={`p-2 text-center ${n && c !== e ? "bg-warn-soft text-warn font-semibold" : ""}`}>{n || ""}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RoutingView({ tenant }: { tenant: string }) {
  const [days, setDays] = useState(28);
  const { data: summary } = useApi<RoutingSummary>(`/api/routing/summary?days=${days}`, [tenant, days]);
  const { data: runs, reload: reloadRuns } = useApi<{ items: Run[] }>("/api/routing/runs", [tenant]);
  const latest = runs?.items.find((r) => r.status === "done");
  const { data: detail, reload: reloadDetail } = useApi<RunDetail>(latest ? `/api/routing/runs/${latest.id}` : null, [tenant, latest?.id]);
  const { data: cases, reload: reloadCases } = useApi<{ items: Case[] }>("/api/routing/cases", [tenant]);
  const { data: agents } = useApi<{ items: { id: string; name: string; mode: string; published_version: unknown }[] }>("/api/agents", [tenant]);
  const [form, setForm] = useState<{ id?: string; utterance: string; expected_agent_id: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  useEvents(["evaluation"], (e) => {
    if (e.type === "routing_run.finished") { setStarting(false); reloadRuns(); reloadDetail(); }
  }, tenant);

  const routable = (agents?.items ?? []).filter((a) => a.published_version && a.mode !== "outbound");

  async function start() {
    setStarting(true);
    try { await api("/api/routing/runs", { method: "POST" }); reloadRuns(); } catch (e) { setStarting(false); setError((e as ApiError).detail); }
  }

  async function saveCase() {
    if (!form) return;
    setError(null);
    try {
      if (form.id) await api(`/api/routing/cases/${form.id}`, { method: "PUT", json: { utterance: form.utterance, expected_agent_id: form.expected_agent_id } });
      else await api("/api/routing/cases", { method: "POST", json: form });
      setForm(null);
      reloadCases();
    } catch (e) {
      setError((e as ApiError).detail);
    }
  }

  if (agents && routable.length === 0) {
    return <EmptyState title="No agents can be routed to yet. Publish an inbound or internal agent with a description and use cases." />;
  }
  const s = latest?.summary;
  return (
    <div className="space-y-4">
      {summary && (
        <Card title="Routing summary" actions={
          <Select className="w-36" aria-label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>Last 7 days</option><option value={28}>Last 28 days</option><option value={90}>Last 90 days</option>
          </Select>}>
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="Decisions" value={summary.decisions} />
            <Stat label="Needed a decision model" value={pct(summary.stage_b_rate)} />
            <Stat label="Fallbacks" value={pct(summary.fallback_rate)} />
            <Stat label="Clarified" value={pct(summary.clarification_rate)} />
            <Stat label="Misrouted" value={pct(summary.misroute_rate)} />
            <Stat label="Decision time p95" value={summary.decision_ms.p95 != null ? `${summary.decision_ms.p95} ms` : "—"} sub={summary.decision_ms.p50 != null ? `p50 ${summary.decision_ms.p50} ms` : undefined} />
          </div>
          {Object.keys(summary.by_method).length > 0 && (
            <p className="mt-3 text-sm text-muted">By method: {Object.entries(summary.by_method).map(([m, n]) => `${m} ${n}`).join(" · ")}</p>
          )}
          {summary.by_agent.length > 0 && (
            <table className="mt-3 w-full text-sm">
              <thead className="text-left text-muted"><tr><th className="py-1">Agent</th><th>Routed to</th><th>Transferred away early</th><th>Out of scope (judge)</th></tr></thead>
              <tbody>{summary.by_agent.map((a) => (
                <tr key={a.agent_id} className="border-t border-[var(--border)]"><td className="py-1">{a.agent_name}</td><td>{a.routed_to}</td><td>{a.early_transfers}</td><td>{a.in_scope_failures}</td></tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      )}
      <Card title="Routing suite" actions={<Button variant="primary" loading={starting} onClick={start}>Run routing suite</Button>}>
        {!runs ? <Spinner /> : !latest ? <p className="text-sm text-muted">No finished runs yet.</p> : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-2xl font-semibold">{pct(s?.accuracy ?? null)}</span>
              {s?.passes ? <Badge tone="ok">Pass</Badge> : <Badge tone="warn">Below target</Badge>}
              <span className="text-sm text-muted">{s?.passed} of {s?.cases} cases · target {pct(s?.pass_mark ?? null)} · p95 {s?.latency_ms?.p95 ?? "—"} ms · {when(latest.created_at)}</span>
            </div>
            {detail ? <Confusion detail={detail} /> : <Spinner />}
            {detail && detail.results.some((r) => !r.passed) && (
              <details>
                <summary className="cursor-pointer text-sm font-medium">Failed cases ({detail.results.filter((r) => !r.passed).length})</summary>
                <ul className="mt-2 space-y-1 text-sm">
                  {detail.results.filter((r) => !r.passed).map((r) => (
                    <li key={r.case_id}>&ldquo;{r.utterance}&rdquo; — expected {r.expected_agent_name}, got {r.chosen_agent_name ?? "none"} <span className="text-muted">({r.method})</span></li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
        {runs && runs.items.length > 1 && (
          <table className="mt-4 w-full text-sm">
            <thead className="text-left text-muted"><tr><th className="py-1">Started</th><th>Trigger</th><th>Status</th><th>Accuracy</th></tr></thead>
            <tbody>{runs.items.map((r) => (
              <tr key={r.id} className="border-t border-[var(--border)]"><td className="py-1">{when(r.created_at)}</td><td>{TRIGGER[r.trigger] ?? r.trigger}</td><td>{r.status}</td><td>{pct(r.summary.accuracy ?? null)}</td></tr>
            ))}</tbody>
          </table>
        )}
      </Card>
      <Card title="Cases" actions={<Button onClick={() => setForm({ utterance: "", expected_agent_id: routable[0]?.id ?? "" })}><Plus size={14} />New case</Button>}>
        {!cases ? <Spinner /> : cases.items.length === 0 ? <p className="text-sm text-muted">No cases yet.</p> : (
          <table className="w-full text-sm">
            <thead className="text-left text-muted"><tr><th className="py-1">Utterance</th><th>Expected agent</th><th>Source</th><th>Enabled</th><th /></tr></thead>
            <tbody>{cases.items.map((c) => (
              <tr key={c.id} className="border-t border-[var(--border)]">
                <td className="py-1 pr-3">{c.utterance}</td>
                <td className="pr-3">{c.expected_agent_name}</td>
                <td className="pr-3"><Badge tone={c.source === "manual" ? "info" : "neutral"}>{c.source === "manual" ? "Manual" : "Generated"}</Badge></td>
                <td className="pr-3"><input type="checkbox" role="switch" aria-label="Enabled" className="accent-[var(--accent)]" checked={c.enabled}
                  onChange={async (e) => { await api(`/api/routing/cases/${c.id}`, { method: "PUT", json: { enabled: e.target.checked } }); reloadCases(); }} /></td>
                <td className="whitespace-nowrap text-right">
                  <Button variant="ghost" aria-label="Edit case" onClick={() => setForm({ id: c.id, utterance: c.utterance, expected_agent_id: c.expected_agent_id })}><Pencil size={14} /></Button>
                  <Button variant="ghost" aria-label="Delete case" onClick={async () => { await api(`/api/routing/cases/${c.id}`, { method: "DELETE" }); reloadCases(); }}><Trash2 size={14} /></Button>
                </td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Card>
      <Modal open={!!form} title={form?.id ? "Edit case" : "New routing case"} onClose={() => setForm(null)}
        footer={<><Button variant="ghost" onClick={() => setForm(null)}>Cancel</Button><Button variant="primary" onClick={saveCase}>Save</Button></>}>
        {form && (
          <div className="space-y-3">
            <Field label="What the caller says"><Input value={form.utterance} onChange={(e) => setForm({ ...form, utterance: e.target.value })} /></Field>
            <Field label="Agent that should get it" error={error}>
              <Select value={form.expected_agent_id} onChange={(e) => setForm({ ...form, expected_agent_id: e.target.value })}>
                {routable.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </Select>
            </Field>
          </div>
        )}
      </Modal>
    </div>
  );
}
