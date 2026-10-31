// Spec: /ui/evaluation.md (Test suites view), /architecture/test-suites.md
"use client";

import { Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, type ApiError, type Persona, type Scenario, type TestResult, type TestRun, useApi, useEvents } from "@/lib/api";
import { label, pct, when } from "@/lib/format";
import { Badge, Button, Card, EmptyState, Field, Input, Modal, Select, Spinner, Textarea, useToast } from "./ui";

const PERSONAS: { id: Persona; label: string }[] = [
  { id: "calm", label: "Calm" }, { id: "confused", label: "Confused" }, { id: "impatient", label: "Impatient" }, { id: "adversarial", label: "Adversarial" },
];
const BUILT_IN = ["search_knowledge", "escalate_to_human", "end_call"];
const TRIGGER: Record<string, string> = { manual: "Manual", builder: "Builder", publish: "On publish" };

export const ratioTone = (passed: number, of: number) => (passed === of ? "ok" : passed === 0 ? "bad" : "warn") as "ok" | "bad" | "warn";

/** UI-51, UI-52: the agent's scenarios, running the suite, the runs and one run's grid. */
export function TestSuitesView({ agentId, tenant, versions, publishedId }: {
  agentId: string; tenant: string; versions: { id: string; version: number }[]; publishedId: string | null;
}) {
  const toast = useToast();
  const { data: scen, reload: reloadScenarios } = useApi<{ items: Scenario[] }>(`/api/agents/${agentId}/scenarios`, [tenant]);
  const { data: runs, reload: reloadRuns } = useApi<{ items: TestRun[] }>(`/api/agents/${agentId}/test-runs`, [tenant]);
  const { data: agent } = useApi<{ draft_config: { tool_ids: string[] } }>(`/api/agents/${agentId}`, [tenant]);
  const { data: tools } = useApi<{ items: { id: string; name: string }[] }>("/api/tools", [tenant]);
  const toolNames = useMemo(() => [...(tools?.items ?? []).filter((t) => agent?.draft_config.tool_ids.includes(t.id)).map((t) => t.name), ...BUILT_IN], [tools, agent]);
  const [editing, setEditing] = useState<Partial<Scenario> | null>(null);
  const [target, setTarget] = useState("published");
  const [repeats, setRepeats] = useState(3);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [openRun, setOpenRun] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const running = runs?.items.find((r) => r.status === "running");

  useEvents(["evaluation"], (e) => {
    if (e.data?.agent_id !== agentId) return;
    if (e.type === "test_run.progress") setProgress({ done: e.data.done, total: e.data.total });
    if (e.type === "test_run.finished") { setProgress(null); reloadRuns(); reloadScenarios(); }
  }, tenant);

  async function run() {
    setStarting(true);
    const body = target === "published" ? { target } : target === "draft" ? { target } : { target: "version", version_id: target };
    try {
      await api(`/api/agents/${agentId}/test-runs`, { method: "POST", json: { ...body, repeats } });
      toast("Test run started", "ok");
      reloadRuns();
    } catch (e) {
      toast((e as ApiError).detail, "bad");
    } finally {
      setStarting(false);
    }
  }
  async function toggle(sc: Scenario) {
    try { await api(`/api/scenarios/${sc.id}`, { method: "PUT", json: { enabled: !sc.enabled } }); reloadScenarios(); } catch (e) { toast((e as ApiError).detail, "bad"); }
  }
  const [deleting, setDeleting] = useState<Scenario | null>(null);
  async function remove(sc: Scenario) {
    try { await api(`/api/scenarios/${sc.id}`, { method: "DELETE" }); setDeleting(null); reloadScenarios(); } catch (e) { toast((e as ApiError).detail, "bad"); }
  }

  if (!scen || !runs) return <Spinner label="Loading test suite…" />;
  const published = versions.find((v) => v.id === publishedId);
  return (
    <div className="space-y-5">
      <Card title="Scenarios" actions={<Button variant="primary" onClick={() => setEditing({})}><Plus size={14} />New scenario</Button>}>
        {scen.items.length === 0 ? (
          <EmptyState title="No test scenarios yet. Add the situations this agent must handle." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="text-left text-xs text-muted [&_th]:pr-3"><tr><th className="pb-2">Scenario</th><th>Persona</th><th>Expected</th><th>Expectations</th><th>Last run</th><th>Enabled</th><th /></tr></thead>
              <tbody>
                {scen.items.map((sc) => (
                  <tr key={sc.id} className="border-t border-line align-top [&_td]:pr-3">
                    <td className="py-2 pr-3"><div className="font-medium">{sc.name}</div><div className="text-xs text-muted">{sc.caller_goal}</div></td>
                    <td><Badge tone={sc.persona === "adversarial" ? "warn" : "neutral"}>{label(sc.persona)}</Badge></td>
                    <td>{label(sc.expected)}</td>
                    <td className="text-xs text-muted">
                      {[sc.required_tools.length && `${sc.required_tools.length} required`, sc.forbidden_tools.length && `${sc.forbidden_tools.length} forbidden`,
                        sc.expected_results.length && `${sc.expected_results.length} results`, sc.memory.length && `${sc.memory.length} memory`].filter(Boolean).join(" · ") || "—"}
                    </td>
                    <td>{sc.last ? <Badge tone={ratioTone(sc.last.passed, sc.last.of)}>{sc.last.passed}/{sc.last.of}</Badge> : <span className="text-muted">—</span>}</td>
                    <td><input type="checkbox" role="switch" aria-label={`Enable ${sc.name}`} className="h-4 w-4 accent-[var(--accent)]" checked={sc.enabled} onChange={() => toggle(sc)} /></td>
                    <td className="whitespace-nowrap text-right">
                      <Button variant="ghost" onClick={() => setEditing(sc)}>Edit</Button>
                      <Button variant="ghost" aria-label={`Delete ${sc.name}`} onClick={() => setDeleting(sc)}><Trash2 size={14} /></Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Run suite">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Target">
            <Select className="w-48" value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="published">{published ? `Published v${published.version}` : "Published"}</option>
              <option value="draft">Draft</option>
              {versions.filter((v) => v.id !== publishedId).map((v) => <option key={v.id} value={v.id}>v{v.version}</option>)}
            </Select>
          </Field>
          <Field label="Repeats"><Input className="w-24" type="number" min={1} max={5} value={repeats} onChange={(e) => setRepeats(Number(e.target.value))} /></Field>
          <Button variant="primary" onClick={run} loading={starting} disabled={!!running}>
            {running ? (progress ? `Running ${progress.done} of ${progress.total}` : "Running…") : "Run suite"}
          </Button>
          <span className="text-xs text-muted">Each scenario is played {repeats} time{repeats === 1 ? "" : "s"}; a scenario passes only if every run passes.</span>
        </div>
      </Card>

      <Card title="Runs">
        {runs.items.length === 0 ? <div className="text-sm text-muted">No runs yet.</div> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="text-left text-xs text-muted"><tr><th className="pb-2">Started</th><th>Target</th><th>Trigger</th><th>Status</th><th>All runs passed</th><th>Pass rate</th><th>Hard fails</th></tr></thead>
              <tbody>
                {runs.items.map((r) => (
                  <tr key={r.id} className="cursor-pointer border-t border-line hover:bg-accent-soft" onClick={() => setOpenRun(r.id)}>
                    <td className="py-2">{when(r.created_at)}</td>
                    <td>{r.target === "draft" ? "Draft" : `v${r.version ?? "?"}`}{r.summary.fidelity === "text_approximation" && <Badge className="ml-1" tone="info">Text approximation</Badge>}</td>
                    <td>{TRIGGER[r.trigger] ?? r.trigger}</td>
                    <td><Badge tone={r.status === "done" ? "ok" : r.status === "failed" ? "bad" : "info"}>{label(r.status)}</Badge></td>
                    <td>{r.summary.scenarios != null ? <Badge tone={ratioTone(r.summary.pass_all ?? 0, r.summary.scenarios)}>{r.summary.pass_all} of {r.summary.scenarios} scenarios</Badge> : "—"}</td>
                    <td>{pct(r.summary.pass_rate)}</td>
                    <td>{r.summary.hard_fails ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {openRun && <RunDetail id={openRun} previous={runs.items.find((r) => r.status === "done" && r.id !== openRun && r.created_at < (runs.items.find((x) => x.id === openRun)?.created_at ?? ""))} onClose={() => setOpenRun(null)} />}
      <Modal open={!!deleting} title="Delete scenario" onClose={() => setDeleting(null)}
        footer={<><Button onClick={() => setDeleting(null)}>Cancel</Button><Button variant="danger" onClick={() => deleting && remove(deleting)}>Delete</Button></>}>
        <p className="text-sm">Delete the scenario “{deleting?.name}”? Finished runs keep their copy.</p>
      </Modal>
      {editing && <ScenarioForm agentId={agentId} value={editing} tools={toolNames} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reloadScenarios(); }} />}
    </div>
  );
}

function RunDetail({ id, previous, onClose }: { id: string; previous?: TestRun; onClose: () => void }) {
  const [run, setRun] = useState<(TestRun & { results: TestResult[] }) | null>(null);
  useEffect(() => { api<TestRun & { results: TestResult[] }>(`/api/test-runs/${id}`).then(setRun).catch(() => setRun(null)); }, [id]);
  const [cell, setCell] = useState<TestResult | null>(null);
  if (!run) return <Card title="Run"><Spinner /></Card>;
  const byScenario = new Map<string, TestResult[]>();
  for (const r of run.results) {
    const key = r.scenario_id ?? r.scenario?.name ?? "?";
    byScenario.set(key, [...(byScenario.get(key) ?? []), r]);
  }
  const texts = (run.summary as { check_texts?: Record<string, string> }).check_texts ?? {};
  const rates = Object.entries(run.summary.check_pass_rates ?? {}).filter(([, v]) => v != null)  // checks that never applied are left out
    .sort(([, a], [, b]) => (a ?? 1) - (b ?? 1));
  return (
    <Card title={`Run of ${when(run.created_at)}`} actions={<Button variant="ghost" onClick={onClose}>Close</Button>}>
      {run.error && <div className="mb-3 rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{run.error}</div>}
      <div className="overflow-x-auto">
        <table className="text-sm">
          <thead className="text-left text-xs text-muted">
            <tr><th className="pb-2 pr-4">Scenario</th>{Array.from({ length: run.repeats }, (_, i) => <th key={i} className="px-2">Run {i + 1}</th>)}{previous && <th className="px-2">vs earlier run</th>}</tr>
          </thead>
          <tbody>
            {[...byScenario.entries()].map(([key, rows]) => {
              const now = rows.filter((r) => r.passed).length;
              const before = previous?.summary.by_scenario?.[key];
              return (
                <tr key={key} className="border-t border-line">
                  <td className="py-2 pr-4">{rows[0].scenario?.name}</td>
                  {rows.sort((a, b) => a.repeat - b.repeat).map((r) => (
                    <td key={r.repeat} className="px-2">
                      <button className={r.passed ? "text-ok" : "text-bad"} aria-label={`${rows[0].scenario?.name} run ${r.repeat}: ${r.passed ? "passed" : "failed"}`} onClick={() => setCell(r)}>{r.passed ? "✓" : "✕"}</button>
                    </td>
                  ))}
                  {previous && <td className="px-2 text-xs">{before ? `${before.passed}/${before.of} → ${now}/${rows.length}` : "new"}</td>}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {cell && (
        <div className="mt-3 rounded-lg border border-line p-3 text-sm">
          <div className="font-medium">{cell.scenario?.name} · run {cell.repeat} · {cell.passed ? "passed" : "failed"}</div>
          {cell.failures.length > 0 && <ul className="mt-1 list-disc pl-5 text-bad">{cell.failures.map((f) => <li key={f}>{f}</li>)}</ul>}
          {cell.call_id && <Link className="mt-1 inline-block text-accent" href={`/calls/detail/?id=${cell.call_id}`}>Open the simulated call</Link>}
        </div>
      )}
      {rates.length > 0 && (
        <div className="mt-4">
          <div className="text-xs font-medium text-muted">Check pass rates in this run</div>
          <ul className="mt-1 grid gap-1 text-xs sm:grid-cols-2 lg:grid-cols-3">
            {rates.map(([k, v]) => (
              <li key={k} className="flex justify-between gap-2 rounded border border-line px-2 py-1" title={texts[k] ?? k}>
                <span className="truncate">{texts[k] ?? k}</span><span className={v != null && v < 1 ? "text-bad" : ""}>{pct(v)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

type KV = { key: string; value: string };
const toKV = (o: Record<string, unknown> | undefined): KV[] => Object.entries(o ?? {}).map(([key, value]) => ({ key, value: String(value) }));
const fromKV = (rows: KV[]) => Object.fromEntries(rows.filter((r) => r.key.trim()).map((r) => [r.key.trim(), r.value]));

function ScenarioForm({ agentId, value, tools, onClose, onSaved }: {
  agentId: string; value: Partial<Scenario>; tools: string[]; onClose: () => void; onSaved: () => void;
}) {
  const p = value.caller_profile ?? {};
  const [f, setF] = useState({
    name: value.name ?? "", caller_goal: value.caller_goal ?? "", persona: value.persona ?? "calm", expected: value.expected ?? "resolved",
    profileName: p.name ?? "", memberId: p.member_id ?? "", dob: p.date_of_birth ?? "",
    extra: toKV(Object.fromEntries(Object.entries(p).filter(([k]) => !["name", "member_id", "date_of_birth"].includes(k)))),
    required: (value.required_tools ?? []).map((r) => ({ name: r.name, args: toKV(r.args) })),
    forbidden: value.forbidden_tools ?? [], results: value.expected_results ?? [], memory: (value.memory ?? []).join("\n"),
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<typeof f>) => setF((x) => ({ ...x, ...patch }));
  async function save() {
    setBusy(true);
    setError(null);
    const profile = { ...(f.profileName ? { name: f.profileName } : {}), ...(f.memberId ? { member_id: f.memberId } : {}), ...(f.dob ? { date_of_birth: f.dob } : {}), ...fromKV(f.extra) };
    const body = {
      name: f.name, caller_goal: f.caller_goal, persona: f.persona, expected: f.expected, caller_profile: profile,
      required_tools: f.required.filter((r) => r.name).map((r) => ({ name: r.name, args: fromKV(r.args) })),
      forbidden_tools: f.forbidden.filter(Boolean), expected_results: f.results.filter((r) => r.tool && r.field),
      memory: f.memory.split("\n").map((m) => m.trim()).filter(Boolean),
    };
    try {
      if (value.id) await api(`/api/scenarios/${value.id}`, { method: "PUT", json: body });
      else await api(`/api/agents/${agentId}/scenarios`, { method: "POST", json: body });
      onSaved();
    } catch (e) {
      setError((e as ApiError).detail);
    } finally {
      setBusy(false);
    }
  }
  const toolSelect = (v: string, onChange: (v: string) => void, aria: string) => (
    <Select aria-label={aria} value={v} onChange={(e) => onChange(e.target.value)}>
      <option value="">Choose a tool</option>
      {tools.map((t) => <option key={t} value={t}>{t}</option>)}
    </Select>
  );
  return (
    <Modal open title={value.id ? "Edit scenario" : "New scenario"} onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={save} loading={busy}>Save scenario</Button></>}>
      <div className="max-h-[65vh] space-y-3 overflow-y-auto pr-1">
        <Field label="Name"><Input value={f.name} maxLength={120} onChange={(e) => set({ name: e.target.value })} /></Field>
        <Field label="Caller's goal" hint="Written to the simulated caller, e.g. “You want to know whether claim C-20931 was paid.”">
          <Textarea maxLength={600} value={f.caller_goal} onChange={(e) => set({ caller_goal: e.target.value })} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Persona"><Select value={f.persona} onChange={(e) => set({ persona: e.target.value as Persona })}>{PERSONAS.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</Select></Field>
          <Field label="Expected outcome"><Select value={f.expected} onChange={(e) => set({ expected: e.target.value as "resolved" | "escalated" })}><option value="resolved">Resolved</option><option value="escalated">Escalated</option></Select></Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Caller name"><Input value={f.profileName} onChange={(e) => set({ profileName: e.target.value })} /></Field>
          <Field label="Member ID"><Input value={f.memberId} onChange={(e) => set({ memberId: e.target.value })} /></Field>
          <Field label="Date of birth"><Input value={f.dob} placeholder="1986-04-12" onChange={(e) => set({ dob: e.target.value })} /></Field>
        </div>
        <KVEditor label="Other caller details" rows={f.extra} onChange={(extra) => set({ extra })} />
        <div className="space-y-2">
          <div className="text-xs font-medium text-muted">Required tools</div>
          {f.required.map((r, i) => (
            <div key={i} className="space-y-1 rounded-lg border border-line p-2">
              <div className="flex gap-2">
                {toolSelect(r.name, (name) => set({ required: f.required.map((x, j) => (j === i ? { ...x, name } : x)) }), "Required tool")}
                <Button variant="ghost" aria-label="Remove required tool" onClick={() => set({ required: f.required.filter((_, j) => j !== i) })}><Trash2 size={14} /></Button>
              </div>
              <KVEditor label="With arguments" rows={r.args} onChange={(args) => set({ required: f.required.map((x, j) => (j === i ? { ...x, args } : x)) })} />
            </div>
          ))}
          <Button variant="ghost" onClick={() => set({ required: [...f.required, { name: "", args: [] }] })}><Plus size={14} />Add required tool</Button>
        </div>
        <div className="space-y-2">
          <div className="text-xs font-medium text-muted">Forbidden tools</div>
          {f.forbidden.map((t, i) => (
            <div key={i} className="flex gap-2">
              {toolSelect(t, (v) => set({ forbidden: f.forbidden.map((x, j) => (j === i ? v : x)) }), "Forbidden tool")}
              <Button variant="ghost" aria-label="Remove forbidden tool" onClick={() => set({ forbidden: f.forbidden.filter((_, j) => j !== i) })}><Trash2 size={14} /></Button>
            </div>
          ))}
          <Button variant="ghost" onClick={() => set({ forbidden: [...f.forbidden, ""] })}><Plus size={14} />Add forbidden tool</Button>
        </div>
        <div className="space-y-2">
          <div className="text-xs font-medium text-muted">Expected tool results</div>
          {f.results.map((r, i) => (
            <div key={i} className="grid gap-2 sm:grid-cols-[1fr_1fr_1fr_auto]">
              {toolSelect(r.tool, (tool) => set({ results: f.results.map((x, j) => (j === i ? { ...x, tool } : x)) }), "Result tool")}
              <Input aria-label="Field" placeholder="status" value={r.field} onChange={(e) => set({ results: f.results.map((x, j) => (j === i ? { ...x, field: e.target.value } : x)) })} />
              <Input aria-label="Equals" placeholder="queued" value={String(r.equals)} onChange={(e) => set({ results: f.results.map((x, j) => (j === i ? { ...x, equals: e.target.value } : x)) })} />
              <Button variant="ghost" aria-label="Remove expected result" onClick={() => set({ results: f.results.filter((_, j) => j !== i) })}><Trash2 size={14} /></Button>
            </div>
          ))}
          <Button variant="ghost" onClick={() => set({ results: [...f.results, { tool: "", field: "", equals: "" }] })}><Plus size={14} />Add expected result</Button>
        </div>
        <Field label="Remembered about the caller (one fact per line, up to 5)" hint="Given to the agent as memory once the caller is verified; never stored.">
          <Textarea value={f.memory} onChange={(e) => set({ memory: e.target.value })} />
        </Field>
        {error && <div role="alert" className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{error}</div>}
      </div>
    </Modal>
  );
}

function KVEditor({ label: text, rows, onChange }: { label: string; rows: KV[]; onChange: (rows: KV[]) => void }) {
  return (
    <div className="space-y-1">
      <div className="text-xs text-muted">{text}</div>
      {rows.map((r, i) => (
        <div key={i} className="grid grid-cols-[1fr_1fr_auto] gap-2">
          <Input aria-label="Key" placeholder="claim_id" value={r.key} onChange={(e) => onChange(rows.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))} />
          <Input aria-label="Value" placeholder="C-20931" value={r.value} onChange={(e) => onChange(rows.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
          <Button variant="ghost" aria-label="Remove" onClick={() => onChange(rows.filter((_, j) => j !== i))}><Trash2 size={14} /></Button>
        </div>
      ))}
      <Button variant="ghost" className="min-h-8 px-3 py-1 text-xs" onClick={() => onChange([...rows, { key: "", value: "" }])}><Plus size={12} />Add</Button>
    </div>
  );
}
