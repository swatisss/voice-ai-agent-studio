// Spec: /ui/insights.md (Needs attention), /architecture/learning-actions.md
"use client";

import Link from "next/link";
import { useState } from "react";
import { api, type ApiError, useApi, useEvents } from "@/lib/api";
import { Badge, Button, Card, Textarea, useToast } from "./ui";

export type Action = {
  id: string; agent_id: string; agent_name: string | null; kind: string; key: string; severity: "high" | "medium"; status: string;
  title: string; detail: string; impact: number; created_at: string;
  evidence: { cluster_id?: string; call_ids?: string[]; version_id?: string; test_run_id?: string; needs_review?: boolean };
};

const KIND: Record<string, string> = {
  fix_not_holding: "Fix did not hold", answer_needed: "Answer needed", check_failing: "Check failing", drift: "Drift",
  scenario_failing: "Test failing",
};

/** Open learning actions, ranked by the API and kept fresh by `action.updated` and learning runs. */
export function useActions(tenant: string, agent = "") {
  const res = useApi<{ items: Action[] }>(`/api/insights/actions${agent ? `?agent_id=${agent}` : ""}`, [tenant, agent]);
  useEvents(["insights"], (e) => {
    if (e.type === "action.updated" || e.type === "learning.run.finished") res.reload();
  }, tenant);
  return res;
}

function NextStep({ a }: { a: Action }) {
  const ev = a.evidence;
  if (a.kind === "fix_not_holding")
    return <span className="flex gap-3"><Link className="text-accent" href={`/insights/cluster/?id=${ev.cluster_id}`}>Open the cluster</Link>
      <Link className="text-accent" href={`/agents/edit/?id=${a.agent_id}`}>Versions (roll back)</Link></span>;
  if (a.kind === "answer_needed") return <Link className="text-accent" href={`/insights/cluster/?id=${ev.cluster_id}`}>See the calls</Link>;
  if (a.kind === "check_failing")
    return (
      <span className="flex flex-wrap gap-2">
        {ev.needs_review ? "Review:" : "Calls:"}
        {(ev.call_ids ?? []).map((id, i) => <Link key={id} className="text-accent" href={`/calls/detail/?id=${id}`}>{i + 1}</Link>)}
        <Link className="text-accent" href={`/evaluation/?agent=${a.agent_id}`}>Evaluation</Link>
      </span>
    );
  if (a.kind === "scenario_failing") return <Link className="text-accent" href={`/evaluation/?agent=${a.agent_id}&view=tests`}>Open the test run</Link>;
  return <Link className="text-accent" href={`/evaluation/?agent=${a.agent_id}`}>Open Evaluation</Link>;
}

/** The reviewer's answer to an `answer_needed` action: it drafts and evaluates a fix (LA-02, UI-68). */
export function AnswerForm({ action, onSent, prompt = "What should the agent tell callers?" }: { action: Action; onSent?: () => void; prompt?: string }) {
  const toast = useToast();
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  async function send() {
    setSending(true);
    try {
      await api(`/api/actions/${action.id}/answer`, { method: "POST", json: { answer: text, by: "Reviewer" } });
      setSent(true);
      onSent?.();
    } catch (e) { toast((e as ApiError).detail, "bad"); } finally { setSending(false); }
  }
  if (sent) return <div className="text-sm text-muted">Drafting and evaluating… the fix appears in Waiting for review.</div>;
  return (
    <div className="space-y-2">
      <Textarea aria-label={prompt} placeholder={prompt} value={text} onChange={(e) => setText(e.target.value)} />
      <Button variant="primary" disabled={text.trim().length < 20} loading={sending} onClick={send}>Save answer & draft fix</Button>
      {text.trim().length > 0 && text.trim().length < 20 && <span className="ml-2 text-xs text-muted">At least 20 characters</span>}
    </div>
  );
}

function Row({ a, reload }: { a: Action; reload: () => void }) {
  const toast = useToast();
  const [answering, setAnswering] = useState(false);
  const [closing, setClosing] = useState<"done" | "dismiss" | null>(null);
  const [note, setNote] = useState("");
  async function close() {
    try { await api(`/api/actions/${a.id}/${closing}`, { method: "POST", json: { by: "Reviewer", note: note.trim() || null } }); reload(); }
    catch (e) { toast((e as ApiError).detail, "bad"); }
  }
  return (
    <li className="space-y-1 border-t border-line py-2 first:border-t-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className={a.severity === "high" ? "h-2 w-2 rounded-full bg-bad" : "h-2 w-2 rounded-full bg-warn"} aria-label={`${a.severity} severity`} />
        <Badge tone={a.severity === "high" ? "bad" : "warn"}>{a.kind === "check_failing" && a.evidence.needs_review ? "Review calls" : KIND[a.kind] ?? a.kind}</Badge>
        <span className="font-medium">{a.title}</span>
        {a.agent_name && <span className="text-xs text-muted">{a.agent_name}</span>}
        <span className="ml-auto flex gap-2">
          {a.kind === "answer_needed" && !answering && <Button variant="primary" onClick={() => setAnswering(true)}>Answer</Button>}
          <Button variant="ghost" onClick={() => setClosing("done")}>Done</Button>
          <Button variant="ghost" onClick={() => setClosing("dismiss")}>Dismiss</Button>
        </span>
      </div>
      <div className="text-sm text-muted">{a.detail}</div>
      <div className="text-sm"><NextStep a={a} /></div>
      {closing && (
        <div className="flex flex-wrap items-center gap-2">
          <input className="min-w-56 flex-1 rounded-lg border border-line bg-panel px-3 py-1.5 text-sm" aria-label="Note (optional)"
            placeholder={closing === "done" ? "Note (optional): what did you do?" : "Note (optional): why dismiss?"} value={note} onChange={(e) => setNote(e.target.value)} />
          <Button variant="primary" onClick={close}>{closing === "done" ? "Mark done" : "Dismiss"}</Button>
          <Button variant="ghost" onClick={() => setClosing(null)}>Cancel</Button>
        </div>
      )}
      {answering && <AnswerForm action={a} onSent={reload} />}
    </li>
  );
}

/** UI-67: Needs attention at the top of Insights. */
export function NeedsAttention({ tenant, agent = "" }: { tenant: string; agent?: string }) {
  const { data, reload } = useActions(tenant, agent);
  const items = data?.items ?? [];
  if (!data || (agent && !items.length)) return null;
  return (
    <Card title={<span>Needs attention {items.length > 0 && <Badge tone="bad">{items.length}</Badge>}</span>}>
      {items.length ? <ul>{items.map((a) => <Row key={a.id} a={a} reload={reload} />)}</ul>
        : <p className="text-sm text-muted">Nothing needs attention. Learning runs list what they find here.</p>}
    </Card>
  );
}
