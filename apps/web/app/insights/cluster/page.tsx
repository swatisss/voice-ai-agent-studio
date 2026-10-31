// Spec: /ui/insights.md (Cluster detail), /architecture/self-learning.md (Gate, Review)
"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { ClusterLabel } from "@/components/cluster-label";
import { FeedbackBadge } from "@/components/feedback";
import { useTenant } from "@/components/shell";
import { Badge, Button, Card, Field, Input, JsonView, Spinner, Textarea, useToast } from "@/components/ui";
import { api, ApiError, useApi, useEvents } from "@/lib/api";
import { label, money, ROOT_CAUSE, secs, when } from "@/lib/format";

export default function Page() {
  return <Suspense fallback={<Spinner />}><ClusterDetail /></Suspense>;
}

function Markdown({ text, mark }: { text: string; mark?: (line: string) => boolean }) {
  return (
    <div className="prose-md text-sm">
      {text.split("\n").map((line, i) => {
        const hl = mark?.(line) ? "rounded bg-ok-soft px-1" : "";
        if (line.startsWith("## ")) return <h2 key={i} className={hl}>{line.slice(3)}</h2>;
        if (line.startsWith("# ")) return <h1 key={i} className={hl}>{line.slice(2)}</h1>;
        if (/^[-*] /.test(line)) return <ul key={i}><li className={hl}>{line.slice(2)}</li></ul>;
        if (!line.trim()) return <div key={i} className="h-2" />;
        return <p key={i} className={hl}>{line}</p>;
      })}
    </div>
  );
}

const CASE_TYPE: Record<string, string> = { cluster: "Cluster", held_out: "Held out", derived: "Derived", regression: "Test scenario" };
const ARTICLE_KINDS = ["knowledge_article", "knowledge_edit"];

type Result = { case_key: string; case_type: string; arm: string; passed: boolean; repeat: number; failures: string[]; call_id: string | null; scenario_name: string | null };

function ClusterDetail() {
  const id = useSearchParams().get("id") ?? "";
  const { tenant } = useTenant();
  const toast = useToast();
  const { data: c, reload } = useApi<any>(id ? `/api/insights/clusters/${id}` : null, [tenant]);
  const proposalId = c?.proposals?.[0]?.id as string | undefined;
  const [p, setP] = useState<any>(null);
  const [editing, setEditing] = useState(false);
  const [draftText, setDraftText] = useState("");
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [rejectNote, setRejectNote] = useState("");
  const [forceNote, setForceNote] = useState<string | null>(null);
  const [approved, setApproved] = useState<{ version: number } | null>(null);
  const [opened, setOpened] = useState<Result[] | null>(null);

  const loadProposal = useCallback(async () => {
    if (!proposalId) return setP(null);
    const d = await api(`/api/proposals/${proposalId}`);
    setP(d);
    if (ARTICLE_KINDS.includes(d.kind)) setDraftText(d.payload.article?.content_markdown ?? "");
    else setDraftText(JSON.stringify(d.payload, null, 2));
  }, [proposalId]);
  useEffect(() => { loadProposal(); }, [loadProposal]);

  useEvents(["insights"], (e) => {
    if (e.type === "eval.progress" && e.data.proposal_id === proposalId) setProgress({ done: e.data.done, total: e.data.total });  // UI-16
    if (e.type === "proposal.updated" && (e.data.cluster_id === id || e.data.id === proposalId)) {  // UI-15
      setBusy(null);
      reload();
      loadProposal();
    }
  }, tenant);

  if (!c) return <Spinner />;

  async function act(name: string, fn: () => Promise<unknown>) {
    setBusy(name);
    try { await fn(); } catch (e) { setBusy(null); toast((e as ApiError).detail, "bad"); }
  }
  const draftFix = () => act("draft", () => api(`/api/insights/clusters/${id}/draft-fix`, { method: "POST" }));
  const evaluate = () => act("eval", async () => { setProgress({ done: 0, total: 1 }); await api(`/api/proposals/${proposalId}/evaluate`, { method: "POST" }); });
  async function saveEdit() {
    const payload = ARTICLE_KINDS.includes(p.kind)
      ? { ...p.payload, article: { title: p.payload.article?.title ?? p.title, content_markdown: draftText } }
      : JSON.parse(draftText);
    await act("save", async () => { await api(`/api/proposals/${proposalId}`, { method: "PUT", json: { payload } }); setEditing(false); setBusy(null); loadProposal(); });
  }
  async function approve(force = false) {
    if (force && !forceNote?.trim()) return toast("Say why you publish although the check failed", "warn");
    setBusy("approve");
    try {
      const r = await api(`/api/proposals/${proposalId}/approve`, { method: "POST", json: { decided_by: "Reviewer", ...(force ? { force: true, note: forceNote } : {}) } });
      setApproved({ version: r.version.version });
      setForceNote(null);
      reload(); loadProposal();
    } catch (e) { toast((e as ApiError).detail, "bad"); } finally { setBusy(null); }
  }
  async function reject() {
    if (!rejectNote.trim()) return toast("Add a note to reject", "warn");
    await act("reject", async () => { await api(`/api/proposals/${proposalId}/reject`, { method: "POST", json: { decided_by: "Reviewer", note: rejectNote } }); setBusy(null); reload(); loadProposal(); });
  }

  const run = p?.eval_run;
  const summary = run?.status === "done" ? run.summary : null;
  const gate = summary?.gate as { passed: boolean; reasons: string[] } | undefined;
  const notReady = !p ? "" : p.status !== "ready" ? "Run an evaluation first" : "";
  const gateFailed = !!summary && gate && !gate.passed;
  const results: Result[] = run?.results ?? [];
  const caseKeys: { key: string; type: string; name: string }[] = [];
  for (const r of results) if (!caseKeys.some((x) => x.key === r.case_key)) caseKeys.push({ key: r.case_key, type: r.case_type, name: r.scenario_name ?? r.case_key });
  const cell = (key: string, arm: string) => {
    const rows = results.filter((x) => x.case_key === key && x.arm === arm);
    if (!rows.length) return <span className="text-muted">…</span>;
    const n = rows.filter((x) => x.passed).length;
    const text = rows.length === 1 ? (n ? "✓" : "✕") : `${n}/${rows.length}`;
    return (
      <button className={n === rows.length ? "text-ok" : n === 0 ? "text-bad" : "text-warn"} onClick={() => setOpened(rows)}
        title={rows.flatMap((x) => x.failures).join("\n") || "Passed"} aria-label={`${key} ${arm}: ${text}`}>{text}</button>
    );
  };
  const original = p?.original_doc?.content as string | undefined;
  const originalLines = new Set((original ?? "").split("\n").map((l) => l.trim()));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Link href="/insights/" className="text-sm text-muted hover:text-fg">Insights</Link><span className="text-muted">/</span>
        <h1 className="text-xl font-semibold">{c.name}</h1>
        <ClusterLabel c={c} />
        <div className="ml-auto flex gap-2">
          {c.ready_for_fix && <Button variant="primary" loading={busy === "draft"} onClick={draftFix}>Draft fix</Button>}
          {c.status === "open" && <Button variant="ghost" onClick={() => act("ignore", async () => { await api(`/api/insights/clusters/${id}/ignore`, { method: "POST" }); setBusy(null); reload(); })}>Ignore</Button>}
        </div>
      </div>
      <p className="text-sm text-muted">{c.description}</p>
      <div className="flex flex-wrap gap-4 text-sm">
        <Badge tone={c.fixable ? "accent" : "neutral"}>{ROOT_CAUSE[c.root_cause]}</Badge>
        <span>{c.escalations_28d} escalations in 28 days</span>
        {c.dislike_count > 0 && <span className="font-medium">{c.dislike_count} not helpful</span>}
        <span>{c.weekly_escalations}/week</span><span className="font-medium">{money(c.est_weekly_cost_usd)}/week</span>
        {c.snoozed_until && new Date(c.snoozed_until) > new Date() && <span className="text-muted">Snoozed until {when(c.snoozed_until)}</span>}
      </div>

      {approved && (
        <div className="flex items-center gap-3 rounded-xl bg-ok-soft px-4 py-3 text-sm text-ok">
          Published v{approved.version} — From fix: {p?.title}
          <Link className="ml-auto" href={`/test-call/?agent=${p?.agent_id}`}><Button variant="primary">Test it now</Button></Link>
        </div>
      )}

      {p && (
        <Card title={<span className="flex flex-wrap items-center gap-2">Proposed fix <Badge tone="info">{label(p.kind)}</Badge>
          <Badge tone={p.origin === "nightly" ? "accent" : "neutral"}>{p.origin === "nightly" ? "Nightly" : "Manual"}</Badge>
          <Badge tone={p.status === "approved" ? "ok" : p.status === "rejected" ? "bad" : "warn"}>{label(p.status)}</Badge></span>}
          actions={p.status === "draft" || p.status === "ready" ? <Button variant="ghost" onClick={() => setEditing(!editing)}>{editing ? "Cancel edit" : "Edit"}</Button> : null}>
          <div className="space-y-3">
            <div className="font-medium">{p.title}</div>
            <p className="text-sm text-muted">{p.rationale}</p>
            {editing ? (
              <div className="space-y-2">
                <Textarea className="mono min-h-64 text-xs" value={draftText} onChange={(e) => setDraftText(e.target.value)} />
                <Button variant="primary" loading={busy === "save"} onClick={saveEdit}>Save (requires re-evaluation)</Button>
              </div>
            ) : p.kind === "knowledge_edit" && original != null ? (
              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-lg border border-line p-3"><div className="mb-1 text-xs font-medium text-muted">Current — {p.original_doc.title}</div><Markdown text={original} /></div>
                <div className="rounded-lg border border-ok p-3"><div className="mb-1 text-xs font-medium text-ok">Revised (changes highlighted)</div>
                  <Markdown text={p.payload.article?.content_markdown ?? ""} mark={(l) => !!l.trim() && !originalLines.has(l.trim())} /></div>
              </div>
            ) : ARTICLE_KINDS.includes(p.kind) ? (
              <div className="rounded-lg border border-line p-3"><Markdown text={p.payload.article?.content_markdown ?? ""} /></div>
            ) : p.kind === "tool_attach" ? (
              <div className="rounded-lg border border-line p-3 text-sm">
                <div>Attach the existing tool <span className="mono font-medium">{p.payload.tool_name}</span></div>
                {p.payload.tool && <div className="mt-1 text-muted">{p.payload.tool.description} <span className="mono">({p.payload.tool.method} {p.payload.tool.url})</span></div>}
              </div>
            ) : (
              <JsonView value={Object.fromEntries(Object.entries(p.payload).filter(([k]) => !["scenarios", "evidence_call_ids"].includes(k)))} collapsed={false} label="Payload" />
            )}
            {(p.payload.scenarios ?? []).length > 0 && (
              <div>
                <div className="text-xs font-medium text-muted">Derived test scenarios (added to the test suite on approval)</div>
                <ul className="mt-1 list-disc pl-5 text-sm">{p.payload.scenarios.map((s: any) => <li key={s.name}>{s.caller_goal}</li>)}</ul>
              </div>
            )}
          </div>
        </Card>
      )}

      {p && p.status !== "rejected" && (
        <Card title="Evaluation" actions={(p.status === "draft" || p.status === "ready") && <Button variant="primary" loading={busy === "eval" || p.status === "evaluating"} onClick={evaluate}>{run ? "Re-run evaluation" : "Run evaluation"}</Button>}>
          {progress && (!summary || p.status === "evaluating") && (
            <div className="mb-3">
              <div className="h-2 overflow-hidden rounded-full bg-neutral-soft"><div className="h-full bg-accent transition-all" style={{ width: `${(100 * progress.done) / Math.max(progress.total, 1)}%` }} /></div>
              <div className="mt-1 text-xs text-muted">{progress.done} of {progress.total} simulated calls</div>
            </div>
          )}
          {summary && (
            <div className="mb-3 space-y-2">
              <div className="rounded-lg bg-accent-soft px-3 py-2 text-sm">
                Baseline {summary.baseline_pass}/{summary.cluster_cases} → Candidate <b>{summary.candidate_pass}/{summary.cluster_cases}</b> ({summary.lift_pct >= 0 ? "+" : ""}{summary.lift_pct} pts)
                {summary.held_out_cases > 0 && <> · Held out {summary.held_out_candidate_pass}/{summary.held_out_cases}</>}
                {" "}· {summary.regression_cases - summary.regression_pass ? `${summary.regression_cases - summary.regression_pass} regressed` : "No regressions"}
                {summary.p95_ms && <> · p95 {secs(summary.p95_ms.baseline)} → {secs(summary.p95_ms.candidate)}</>} · {summary.duration_s}s
              </div>
              {gate && (
                <div className={gate.passed ? "rounded-lg bg-ok-soft px-3 py-2 text-sm text-ok" : "rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad"} role="status">
                  <b>{gate.passed ? "Check passed" : "Check failed"}</b>
                  {!gate.passed && <ul className="mt-1 list-disc pl-5">{gate.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
                </div>
              )}
            </div>
          )}
          {run?.status === "failed" && <div className="mb-3 text-sm text-bad">Evaluation failed: {run.error}</div>}
          {caseKeys.length > 0 ? (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted"><tr><th className="pb-2">Case</th><th>Type</th><th className="text-center">Current version</th><th className="text-center">With the fix</th></tr></thead>
              <tbody>{caseKeys.map((k) => (
                <tr key={k.key} className="border-t border-line"><td className="py-1.5">{k.name}</td><td>{CASE_TYPE[k.type] ?? label(k.type)}</td>
                  <td className="text-center">{cell(k.key, "baseline")}</td><td className="text-center">{cell(k.key, "candidate")}</td></tr>
              ))}</tbody>
            </table>
          ) : <div className="text-sm text-muted">Simulated callers replay this cluster's calls, calls held back from drafting, derived scenarios and the agent's test suite against the current version and the fix.</div>}
          {opened && (
            <div className="mt-3 rounded-lg border border-line p-3 text-sm">
              <div className="flex items-center"><b>{opened[0].scenario_name ?? opened[0].case_key} · {opened[0].arm === "baseline" ? "current version" : "with the fix"}</b>
                <button className="ml-auto text-xs text-muted" onClick={() => setOpened(null)}>Close</button></div>
              <ul className="mt-1 space-y-1">
                {opened.map((r) => (
                  <li key={r.repeat}>Run {r.repeat}: {r.passed ? <span className="text-ok">passed</span> : <span className="text-bad">{r.failures.join("; ") || "failed"}</span>}
                    {r.call_id && <Link className="ml-2 text-accent" href={`/calls/detail/?id=${r.call_id}`}>Call</Link>}</li>
                ))}
              </ul>
            </div>
          )}
          {(p.status === "ready" || p.status === "draft") && (
            <div className="mt-4 space-y-3 border-t border-line pt-3">
              <div className="flex flex-wrap items-end gap-2">
                <Button variant="primary" disabled={!!notReady || gateFailed} loading={busy === "approve" && forceNote === null} onClick={() => approve(false)}>Approve & publish</Button>
                {notReady && <span className="text-xs text-muted">{notReady}</span>}
                {gateFailed && forceNote === null && <button className="text-xs text-accent underline" onClick={() => setForceNote("")}>Publish anyway</button>}
                <div className="ml-auto flex items-end gap-2">
                  <Field label="Reject note" hint="The next nights skip this cluster for a while"><Input value={rejectNote} onChange={(e) => setRejectNote(e.target.value)} /></Field>
                  <Button variant="danger" onClick={reject}>Reject</Button>
                </div>
              </div>
              {forceNote !== null && (
                <div className="flex flex-wrap items-end gap-2 rounded-lg bg-warn-soft p-3">
                  <Field label="Why publish although the check failed?"><Input className="w-96" value={forceNote} onChange={(e) => setForceNote(e.target.value)} /></Field>
                  <Button variant="danger" loading={busy === "approve"} onClick={() => approve(true)}>Publish anyway</Button>
                  <Button variant="ghost" onClick={() => setForceNote(null)}>Cancel</Button>
                </div>
              )}
            </div>
          )}
        </Card>
      )}

      <Card title={`Evidence (${c.calls.length} calls)`}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted"><tr><th className="pb-2">Date</th><th>Caller goal</th><th>Gap</th><th>Specialist resolution</th><th>Caller feedback</th><th /></tr></thead>
            <tbody>{c.calls.map((e: any) => (
              <tr key={e.call_id} className="border-t border-line align-top">
                <td className="py-2 whitespace-nowrap">{when(e.date)}</td><td>{e.caller_goal}</td><td className="text-muted">{e.gap_summary}</td>
                <td>{e.resolution_note || <span className="text-muted">—</span>}</td>
                <td>{e.feedback ? <div className="space-y-1"><FeedbackBadge rating={e.feedback.rating} />{e.feedback.comment && <div className="text-xs text-muted">{e.feedback.comment}</div>}</div> : <span className="text-muted">—</span>}</td>
                <td><Link className="text-accent" href={`/calls/detail/?id=${e.call_id}`}>Call</Link></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
