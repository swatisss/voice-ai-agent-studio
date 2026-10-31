// Spec: /ui/evaluation.md
"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { FeedbackBadge } from "@/components/feedback";
import { GROUPS, SOURCE, VERDICT } from "@/components/scorecard";
import { useTenant } from "@/components/shell";
import { Badge, Button, Card, EmptyState, Select, Spinner, Stat } from "@/components/ui";
import { useApi, useEvents, type Verdict } from "@/lib/api";
import { label, outcomeTone, pct, secs, when } from "@/lib/format";

type VersionRow = {
  version_id: string; version: number | null; published_at: string | null; calls: number; scored: number;
  containment_rate: number | null; correct_escalation_rate: number | null; unnecessary_escalation_rate: number | null;
  abandonment_rate: number | null; hard_fail_calls: number; thumbs_up_rate: number | null; first_response_ms: number | null;
  latency_p50_ms: number | null; latency_p95_ms: number | null; drift: string[]; check_pass_rates: Record<string, number | null>;
};
type CheckRow = {
  key: string; group: string; method: "code" | "judge"; hard_gate: boolean; text: string; source: "built_in" | "config" | "custom";
  pass_rate: number | null; decided: number; reviews: number; agreement: number | null; catch_rate: number | null;
  baseline: number | null; calibrated: boolean | null;
};
type Summary = { versions: VersionRow[]; checks: CheckRow[]; daily: { date: string; calls: number; containment_rate: number | null; goal_met_rate: number | null; grounded_rate: number | null; hard_fails: number }[] };
type Scored = { call_id: string; started_at: string; version: number | null; outcome: string | null; feedback: "up" | "down" | null; score: number | null; hard_fail: boolean; judged: boolean; failed_checks: string[]; review_count: number };

const DRIFT_NOTE = "Lower than in this version's first week";
const SHORT: Record<string, string> = {
  "outcome.goal_met": "Goal met", "outcome.escalation_appropriate": "Right escalation", "knowledge.grounded": "Grounded",
  "knowledge.admits_unknown": "Admits unknowns", "tools.right_use": "Right tool use", "tools.succeeded": "Tools succeeded",
  "memory.used_correctly": "Memory used well", "responsiveness.latency": "Fast responses", "safety.no_clinical_advice": "No clinical advice",
  "safety.minimum_necessary": "Minimum necessary", "safety.phi_before_verification": "Verified before member data",
  "safety.memory_before_verification": "Verified before memory",
};
const checkName = (c: { key: string; text: string }) => SHORT[c.key] ?? c.text;
const pts = (a: number | null | undefined, b: number | null | undefined) =>
  a == null || b == null ? null : Math.round((a - b) * 100);

export default function Page() {
  return <Suspense fallback={<Spinner />}><Evaluation /></Suspense>;
}

function Evaluation() {
  const params = useSearchParams();
  const router = useRouter();
  const { tenant } = useTenant();
  const { data: agents } = useApi<{ items: { id: string; name: string; published_version: { id: string; version: number } | null }[] }>("/api/agents", [tenant]);
  const agentId = params.get("agent") || agents?.items[0]?.id || "";
  const agent = agents?.items.find((a) => a.id === agentId);
  const [days, setDays] = useState(28);
  const [includeSeed, setIncludeSeed] = useState(true);
  const q = `agent_id=${agentId}&days=${days}&include_seed=${includeSeed}`;
  const { data, reload, error } = useApi<Summary>(agentId ? `/api/evaluation/summary?${q}` : null, [tenant]);
  const [filters, setFilters] = useState<{ version_id?: string; check?: string; verdict?: string; hard_fail?: boolean; reviewed?: boolean }>({});
  const listQ = useMemo(() => {
    const p = new URLSearchParams(q);
    for (const [k, v] of Object.entries(filters)) if (v !== undefined && v !== "") p.set(k, String(v));
    return p.toString();
  }, [q, filters]);
  const { data: scored, reload: reloadList } = useApi<{ items: Scored[] }>(agentId ? `/api/evaluation/scorecards?${listQ}` : null, [tenant]);
  const last = useRef(0);
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEvents(["evaluation"], (e) => {  // at most one refresh every 5 s
    if (e.type !== "scorecard.updated" || e.data?.agent_id !== agentId || pending.current) return;
    const wait = Math.max(0, 5000 - (Date.now() - last.current));
    pending.current = setTimeout(() => { pending.current = null; last.current = Date.now(); reload(); reloadList(); }, wait);
  }, tenant);
  useEffect(() => () => { if (pending.current) clearTimeout(pending.current); }, []);
  const [compare, setCompare] = useState<string[]>([]);
  const listRef = useRef<HTMLDivElement>(null);

  if (!agents) return <Spinner label="Loading agents…" />;
  const controls = (
    <div className="flex flex-wrap items-center gap-3">
      <h1 className="mr-auto text-xl font-semibold">Evaluation</h1>
      <Select className="w-56" aria-label="Agent" value={agentId} onChange={(e) => { setFilters({}); setCompare([]); router.replace(`/evaluation/?agent=${e.target.value}`); }}>
        {agents.items.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
      </Select>
      <Select className="w-36" aria-label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))}>
        <option value={7}>Last 7 days</option><option value={28}>Last 28 days</option><option value={90}>Last 90 days</option>
      </Select>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" className="h-4 w-4 accent-[var(--accent)]" checked={includeSeed} onChange={(e) => setIncludeSeed(e.target.checked)} />
        Include seeded history
      </label>
    </div>
  );
  if (error) return <div className="space-y-4">{controls}<div className="text-sm text-bad">{error.detail}</div></div>;
  if (!data) return <div className="space-y-4">{controls}<Spinner label="Loading scores…" /></div>;
  const scoredTotal = data.versions.reduce((n, v) => n + v.scored, 0);
  if (!scoredTotal) {  // UI-50
    return (
      <div className="space-y-4">
        {controls}
        <EmptyState title="No scored calls for this agent yet. Calls are scored automatically after they end.">
          <Link className="font-medium text-accent" href={`/test-call/?agent=${agentId}`}>Test call</Link>
        </EmptyState>
      </div>
    );
  }
  const current = data.versions.find((v) => v.version_id === agent?.published_version?.id) ?? data.versions[0];
  const previous = data.versions.find((v) => (v.version ?? 0) < (current.version ?? 0) && v.scored > 0);
  const rate = (v: VersionRow | undefined, key: string) => v?.check_pass_rates[key] ?? null;
  const tiles: { label: string; value: string; drift?: boolean; delta: number | null; tone?: "bad" }[] = [
    { label: "Goal met", value: pct(rate(current, "outcome.goal_met")), drift: current.drift.includes("goal_met"), delta: pts(rate(current, "outcome.goal_met"), rate(previous, "outcome.goal_met")) },
    { label: "Containment", value: pct(current.containment_rate), drift: current.drift.includes("containment"), delta: pts(current.containment_rate, previous?.containment_rate) },
    { label: "Grounded", value: pct(rate(current, "knowledge.grounded")), drift: current.drift.includes("grounded"), delta: pts(rate(current, "knowledge.grounded"), rate(previous, "knowledge.grounded")) },
    { label: "Hard fails", value: String(current.hard_fail_calls), delta: previous ? current.hard_fail_calls - previous.hard_fail_calls : null, tone: current.hard_fail_calls > 0 ? "bad" : undefined },
    { label: "p95 response time", value: secs(current.latency_p95_ms), delta: null },
    { label: "Helpful", value: pct(current.thumbs_up_rate), delta: pts(current.thumbs_up_rate, previous?.thumbs_up_rate) },
  ];
  const trend = data.daily.map((d) => ({
    date: d.date.slice(5), goal: d.goal_met_rate == null ? null : Math.round(d.goal_met_rate * 100),
    containment: d.containment_rate == null ? null : Math.round(d.containment_rate * 100),
    grounded: d.grounded_rate == null ? null : Math.round(d.grounded_rate * 100), hard: d.hard_fails,
  }));
  const publishMarks = data.versions.filter((v) => v.published_at && trend.some((t) => t.date === v.published_at!.slice(5, 10)));
  const pair = compare.map((id) => data.versions.find((v) => v.version_id === id)).filter(Boolean) as VersionRow[];
  const showFailing = (key: string) => {
    setFilters({ check: key, verdict: "fail" });
    requestAnimationFrame(() => listRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  return (
    <div className="space-y-5">
      {controls}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {tiles.map((t) => (
          <Stat key={t.label} label={t.label} value={<span className={t.tone === "bad" ? "text-bad" : undefined}>{t.value}</span>}
            sub={<span className="flex flex-wrap items-center gap-1">
              {t.delta != null && previous && <span>{t.delta > 0 ? "+" : ""}{t.delta}{t.label === "Hard fails" ? "" : " pts"} vs v{previous.version}</span>}
              {t.drift && <Badge tone="warn" className="cursor-help"><span title={DRIFT_NOTE}>Drift</span></Badge>}
              {t.drift && <span className="sr-only">{DRIFT_NOTE}</span>}
            </span>} />
        ))}
      </div>
      <p className="-mt-2 text-xs text-muted">Tiles show v{current.version} ({current.scored} scored calls in the period).</p>

      <Card title="Trend">
        <div className="h-64">
          <ResponsiveContainer>
            <ComposedChart data={trend} margin={{ left: -20, right: 10 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
              <XAxis dataKey="date" stroke="var(--muted)" fontSize={12} />
              <YAxis yAxisId="pct" domain={[0, 100]} unit="%" stroke="var(--muted)" fontSize={12} />
              <YAxis yAxisId="n" orientation="right" allowDecimals={false} stroke="var(--muted)" fontSize={12} />
              <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--border)" }} />
              <Legend />
              <Bar yAxisId="n" dataKey="hard" name="Hard fails" fill="var(--chart-warn)" radius={[3, 3, 0, 0]} />
              <Line yAxisId="pct" type="linear" dataKey="goal" name="Goal met" stroke="var(--accent)" strokeWidth={2} dot={false} connectNulls />
              <Line yAxisId="pct" type="linear" dataKey="containment" name="Containment" stroke="var(--muted)" strokeWidth={2} strokeDasharray="5 3" dot={false} connectNulls />
              <Line yAxisId="pct" type="linear" dataKey="grounded" name="Grounded" stroke="var(--ok)" strokeWidth={2} dot={false} connectNulls />
              {publishMarks.map((v) => <ReferenceLine key={v.version_id} yAxisId="pct" x={v.published_at!.slice(5, 10)} stroke="var(--muted)" strokeDasharray="4 4" label={{ value: `v${v.version}`, fontSize: 11, fill: "var(--muted)" }} />)}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card title="Versions" actions={<span className="text-xs text-muted">Select two versions to compare their checks</span>}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-sm">
            <thead className="text-left text-xs text-muted">
              <tr><th className="pb-2" /><th>Version</th><th>Calls</th><th>Scored</th><th>Containment</th><th>Correct esc.</th><th>Unneeded esc.</th>
                <th>Abandoned</th><th>Goal met</th><th>Grounded</th><th>Tool success</th><th>Hard fails</th><th>p50 / p95</th><th>Helpful</th></tr>
            </thead>
            <tbody>
              {data.versions.map((v) => (
                <tr key={v.version_id} className="border-t border-line">
                  <td className="py-2 pr-2">
                    <input type="checkbox" aria-label={`Compare v${v.version}`} className="h-4 w-4 accent-[var(--accent)]" checked={compare.includes(v.version_id)}
                      onChange={(e) => setCompare((c) => (e.target.checked ? [...c, v.version_id].slice(-2) : c.filter((x) => x !== v.version_id)))} />
                  </td>
                  <td><Badge tone="ok">v{v.version}</Badge> <span className="text-xs text-muted">{when(v.published_at)}</span>
                    {v.drift.length > 0 && <Badge tone="warn" className="ml-1">Drift</Badge>}</td>
                  <td>{v.calls}</td><td>{v.scored}</td><td>{pct(v.containment_rate)}</td><td>{pct(v.correct_escalation_rate)}</td>
                  <td>{pct(v.unnecessary_escalation_rate)}</td><td>{pct(v.abandonment_rate)}</td><td>{pct(rate(v, "outcome.goal_met"))}</td>
                  <td>{pct(rate(v, "knowledge.grounded"))}</td><td>{pct(rate(v, "tools.succeeded"))}</td><td>{v.hard_fail_calls}</td>
                  <td className="whitespace-nowrap">{secs(v.latency_p50_ms)} / {secs(v.latency_p95_ms)}</td><td>{pct(v.thumbs_up_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {pair.length === 2 && (
          <div className="mt-4">
            <div className="text-xs font-medium text-muted">Pass rate, v{pair[1].version} compared with v{pair[0].version}</div>
            <ul className="mt-1 grid gap-1 text-sm sm:grid-cols-2">
              {data.checks.map((c) => {
                const d = pts(pair[1].check_pass_rates[c.key], pair[0].check_pass_rates[c.key]);
                return (
                  <li key={c.key} className="flex justify-between gap-2 rounded border border-line px-2 py-1">
                    <span className="truncate">{checkName(c)}</span>
                    <span className={d == null ? "text-muted" : d < 0 ? "text-bad" : d > 0 ? "text-ok" : ""}>{d == null ? "—" : `${d > 0 ? "+" : ""}${d} pts`}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </Card>

      <Card title="Checks">
        <div className="space-y-4">
          {GROUPS.map((g) => {
            const rows = data.checks.filter((c) => c.group === g.id);
            if (!rows.length) return null;
            return (
              <div key={g.id}>
                <div className="text-xs font-medium text-muted">{g.label}</div>
                <ul className="mt-1 divide-y divide-line rounded-lg border border-line">
                  {rows.map((c) => (
                    <li key={c.key}>
                      <button className="flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent-soft" onClick={() => showFailing(c.key)}
                        aria-label={`${checkName(c)}: show failed calls`}>
                        <span className="min-w-0 flex-1">
                          <span className="font-medium">{checkName(c)}</span>
                          {SHORT[c.key] && <span className="block text-xs text-muted">{c.text}</span>}
                        </span>
                        <Badge tone={c.method === "code" ? "info" : "neutral"}>{c.method === "code" ? "Code" : "Judge"}</Badge>
                        {c.hard_gate && <Badge tone="warn">Hard gate</Badge>}
                        <Badge>{SOURCE[c.source]}</Badge>
                        <span className="w-28 text-right tabular-nums">{pct(c.pass_rate)} <span className="text-xs text-muted">of {c.decided}</span></span>
                        {c.method === "judge" && (
                          <span className="flex w-64 items-center justify-end gap-1.5 text-xs text-muted">
                            <span title="Agreement · catch rate · baseline">{c.reviews} reviews · {pct(c.agreement)} · {pct(c.catch_rate)} · {pct(c.baseline)}</span>
                            {c.calibrated ? <Badge tone="ok">Calibrated</Badge> : <Badge><span title="Needs 20 reviews at 85 % agreement">Uncalibrated</span></Badge>}
                          </span>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      </Card>

      <div ref={listRef} className="scroll-mt-4">
        <Card title="Scored calls" actions={Object.keys(filters).length > 0 && <Button variant="ghost" onClick={() => setFilters({})}>Clear filters</Button>}>
          <div className="mb-3 flex flex-wrap gap-2">
            <Select className="w-32" aria-label="Version" value={filters.version_id ?? ""} onChange={(e) => setFilters((f) => ({ ...f, version_id: e.target.value || undefined }))}>
              <option value="">All versions</option>
              {data.versions.map((v) => <option key={v.version_id} value={v.version_id}>v{v.version}</option>)}
            </Select>
            <Select className="w-56" aria-label="Check" value={filters.check ?? ""} onChange={(e) => setFilters((f) => ({ ...f, check: e.target.value || undefined }))}>
              <option value="">Any check</option>
              {data.checks.map((c) => <option key={c.key} value={c.key}>{checkName(c)}</option>)}
            </Select>
            <Select className="w-36" aria-label="Verdict" value={filters.verdict ?? ""} onChange={(e) => setFilters((f) => ({ ...f, verdict: e.target.value || undefined }))}>
              <option value="">Any verdict</option>
              {(Object.keys(VERDICT) as Verdict[]).map((v) => <option key={v} value={v}>{VERDICT[v].label}</option>)}
            </Select>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="h-4 w-4 accent-[var(--accent)]" checked={!!filters.hard_fail} onChange={(e) => setFilters((f) => ({ ...f, hard_fail: e.target.checked || undefined }))} />Hard fail only
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="h-4 w-4 accent-[var(--accent)]" checked={filters.reviewed === false} onChange={(e) => setFilters((f) => ({ ...f, reviewed: e.target.checked ? false : undefined }))} />Not yet reviewed
            </label>
          </div>
          {!scored ? <Spinner /> : scored.items.length === 0 ? <div className="text-sm text-muted">No calls match.</div> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="text-left text-xs text-muted"><tr><th className="pb-2">Started</th><th>Version</th><th>Outcome</th><th>Feedback</th><th>Score</th><th>Failed checks</th><th>Reviewed</th></tr></thead>
                <tbody>
                  {scored.items.map((r) => (
                    <tr key={r.call_id} className="cursor-pointer border-t border-line hover:bg-accent-soft" onClick={() => router.push(`/calls/detail/?id=${r.call_id}`)}>
                      <td className="py-2"><Link href={`/calls/detail/?id=${r.call_id}`} onClick={(e) => e.stopPropagation()}>{when(r.started_at)}</Link></td>
                      <td>v{r.version}</td>
                      <td><Badge tone={outcomeTone(r.outcome)}>{label(r.outcome)}</Badge></td>
                      <td><FeedbackBadge rating={r.feedback} /></td>
                      <td className="tabular-nums">{pct(r.score)} {r.hard_fail && <Badge tone="bad">Hard fail</Badge>}</td>
                      <td className="text-xs">
                        {r.failed_checks.slice(0, 3).map((k) => SHORT[k] ?? data.checks.find((c) => c.key === k)?.text ?? k).join(", ")}
                        {r.failed_checks.length > 3 && ` +${r.failed_checks.length - 3}`}
                      </td>
                      <td>{r.review_count || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
