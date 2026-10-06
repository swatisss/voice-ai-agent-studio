// Spec: /ui/insights.md (Cluster detail)
"use client";

import { CheckCircle2, XCircle } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { ClusterLabel } from "@/components/cluster-label";
import { useTenant } from "@/components/shell";
import { Badge, Button, Card, Field, Input, JsonView, Spinner, Textarea, useToast } from "@/components/ui";
import { api, ApiError, useApi, useEvents } from "@/lib/api";
import { label, money, ROOT_CAUSE, when } from "@/lib/format";

export default function Page() {
  return <Suspense fallback={<Spinner />}><ClusterDetail /></Suspense>;
}

function Markdown({ text }: { text: string }) {
  return (
    <div className="prose-md text-sm">
      {text.split("\n").map((line, i) => {
        if (line.startsWith("## ")) return <h2 key={i}>{line.slice(3)}</h2>;
        if (line.startsWith("# ")) return <h1 key={i}>{line.slice(2)}</h1>;
        if (/^[-*] /.test(line)) return <ul key={i}><li>{line.slice(2)}</li></ul>;
        if (!line.trim()) return <div key={i} className="h-2" />;
        return <p key={i}>{line}</p>;
      })}
    </div>
  );
}

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
  const [live, setLive] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [rejectNote, setRejectNote] = useState("");
  const [approved, setApproved] = useState<{ version: number } | null>(null);

  const loadProposal = useCallback(async () => {
    if (!proposalId) return setP(null);
    const d = await api(`/api/proposals/${proposalId}`);
    setP(d);
    if (d.kind === "knowledge_article") setDraftText(d.payload.article?.content_markdown ?? "");
    else setDraftText(JSON.stringify(d.payload, null, 2));
  }, [proposalId]);
  useEffect(() => { loadProposal(); }, [loadProposal]);

  useEvents(["insights"], (e) => {
    if (e.type === "eval.progress" && e.data.proposal_id === proposalId) {  // UI-16
      setProgress({ done: e.data.done, total: e.data.total });
      setLive((m) => ({ ...m, [`${e.data.last.case_key}|${e.data.last.arm}`]: e.data.last.passed }));
    }
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
  const evaluate = () => act("eval", async () => { setLive({}); setProgress({ done: 0, total: 1 }); await api(`/api/proposals/${proposalId}/evaluate`, { method: "POST" }); });
  async function saveEdit() {
    const payload = p.kind === "knowledge_article"
      ? { article: { title: p.payload.article?.title ?? p.title, content_markdown: draftText } }
      : JSON.parse(draftText);
    await act("save", async () => { await api(`/api/proposals/${proposalId}`, { method: "PUT", json: { payload } }); setEditing(false); setBusy(null); loadProposal(); });
  }
  async function approve() {
    setBusy("approve");
    try {
      const r = await api(`/api/proposals/${proposalId}/approve`, { method: "POST", json: { decided_by: "Reviewer" } });
      setApproved({ version: r.version.version });
      reload(); loadProposal();
    } catch (e) { toast((e as ApiError).detail, "bad"); } finally { setBusy(null); }
  }
  async function reject() {
    if (!rejectNote.trim()) return toast("Add a note to reject", "warn");
    await act("reject", async () => { await api(`/api/proposals/${proposalId}/reject`, { method: "POST", json: { decided_by: "Reviewer", note: rejectNote } }); setBusy(null); reload(); loadProposal(); });
  }

  const run = p?.eval_run;
  const summary = run?.status === "done" ? run.summary : null;
  const regressFail = summary ? summary.regression_cases - summary.regression_pass : 0;
  const worse = summary ? summary.candidate_pass < summary.baseline_pass : false;
  const approveBlock = !p ? "" : p.status !== "ready" ? "Run an evaluation first" : regressFail ? `${regressFail} regression${regressFail > 1 ? "s" : ""} failed` : worse ? "Candidate scored below baseline" : "";  // UI-17
  const cases: { key: string; type: string }[] = [];
  for (const r of run?.results ?? []) if (!cases.some((x) => x.key === r.case_key)) cases.push({ key: r.case_key, type: r.case_type });
  for (const k of Object.keys(live)) { const key = k.split("|")[0]; if (!cases.some((x) => x.key === key)) cases.push({ key, type: key.startsWith("cluster-") ? "cluster" : "regression" }); }
  const cell = (key: string, arm: string) => {
    const r = run?.results?.find((x: any) => x.case_key === key && x.arm === arm);
    const v = r ? r.passed : live[`${key}|${arm}`];
    if (v === undefined) return <span className="text-muted">{arm === "baseline" && key && !key.startsWith("cluster-") ? "—" : "…"}</span>;
    return <span title={r?.judge?.notes ?? ""}>{v ? <CheckCircle2 size={16} className="inline text-ok" /> : <XCircle size={16} className="inline text-bad" />}</span>;
  };

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
        <span>{c.escalations_28d} escalations in 28 days</span><span>{c.weekly_escalations}/week</span><span className="font-medium">{money(c.est_weekly_cost_usd)}/week</span>
      </div>

      {approved && (
        <div className="flex items-center gap-3 rounded-xl bg-ok-soft px-4 py-3 text-sm text-ok">
          Published v{approved.version} — From fix: {p?.title}
          <Link className="ml-auto" href={`/test-call/?agent=${p?.agent_id}`}><Button variant="primary">Test it now</Button></Link>
        </div>
      )}

      {p && (
        <Card title={<span className="flex items-center gap-2">Proposed fix <Badge tone="info">{label(p.kind)}</Badge><Badge tone={p.status === "approved" ? "ok" : p.status === "rejected" ? "bad" : "warn"}>{label(p.status)}</Badge></span>}
          actions={p.status === "draft" || p.status === "ready" ? <Button variant="ghost" onClick={() => setEditing(!editing)}>{editing ? "Cancel edit" : "Edit"}</Button> : null}>
          <div className="space-y-3">
            <div className="font-medium">{p.title}</div>
            <p className="text-sm text-muted">{p.rationale}</p>
            {editing ? (
              <div className="space-y-2">
                <Textarea className="mono min-h-64 text-xs" value={draftText} onChange={(e) => setDraftText(e.target.value)} />
                <Button variant="primary" loading={busy === "save"} onClick={saveEdit}>Save (requires re-evaluation)</Button>
              </div>
            ) : p.kind === "knowledge_article" ? (
              <div className="rounded-lg border border-line p-3"><Markdown text={p.payload.article?.content_markdown ?? ""} /></div>
            ) : (
              <JsonView value={p.payload} collapsed={false} label="Payload" />
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
            <div className="mb-3 rounded-lg bg-accent-soft px-3 py-2 text-sm">
              Baseline {summary.baseline_pass}/{summary.cluster_cases} → Candidate <b>{summary.candidate_pass}/{summary.cluster_cases}</b> ({summary.lift_pct >= 0 ? "+" : ""}{summary.lift_pct} pts) · Regressions {summary.regression_pass}/{summary.regression_cases} passed · {summary.duration_s}s
            </div>
          )}
          {run?.status === "failed" && <div className="mb-3 text-sm text-bad">Evaluation failed: {run.error}</div>}
          {cases.length > 0 ? (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted"><tr><th className="pb-2">Case</th><th>Type</th><th className="text-center">Baseline</th><th className="text-center">Candidate</th></tr></thead>
              <tbody>{cases.map((k) => (
                <tr key={k.key} className="border-t border-line"><td className="py-1.5">{k.key}</td><td>{label(k.type)}</td><td className="text-center">{k.type === "cluster" ? cell(k.key, "baseline") : <span className="text-muted">—</span>}</td><td className="text-center">{cell(k.key, "candidate")}</td></tr>
              ))}</tbody>
            </table>
          ) : <div className="text-sm text-muted">Simulated callers replay this cluster's calls against the current version and the fix, plus regression scenarios.</div>}
          {(p.status === "ready" || p.status === "draft") && (
            <div className="mt-4 flex flex-wrap items-end gap-2 border-t border-line pt-3">
              <Button variant="primary" disabled={!!approveBlock} loading={busy === "approve"} onClick={approve}>Approve & publish</Button>
              {approveBlock && <span className="text-xs text-muted">{approveBlock}</span>}
              <div className="ml-auto flex items-end gap-2"><Field label="Reject note"><Input value={rejectNote} onChange={(e) => setRejectNote(e.target.value)} /></Field><Button variant="danger" onClick={reject}>Reject</Button></div>
            </div>
          )}
        </Card>
      )}

      <Card title={`Evidence (${c.calls.length} calls)`}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted"><tr><th className="pb-2">Date</th><th>Caller goal</th><th>Gap</th><th>Specialist resolution</th><th /></tr></thead>
            <tbody>{c.calls.map((e: any) => (
              <tr key={e.call_id} className="border-t border-line align-top">
                <td className="py-2 whitespace-nowrap">{when(e.date)}</td><td>{e.caller_goal}</td><td className="text-muted">{e.gap_summary}</td>
                <td>{e.resolution_note || <span className="text-muted">—</span>}</td>
                <td><Link className="text-accent" href={`/calls/detail/?id=${e.call_id}`}>Call</Link></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
