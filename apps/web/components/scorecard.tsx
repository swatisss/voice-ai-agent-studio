// Spec: /ui/calls.md (Detail: Scorecard card), /ui/evaluation.md, /architecture/call-scoring.md
"use client";

import { useEffect, useState } from "react";
import { api, type ApiError, type CallEvent, type CheckGroup, type Scorecard, type ScoreCheck, type Verdict } from "@/lib/api";
import { pct, secs } from "@/lib/format";
import type { Tone } from "@/lib/format";
import { Badge, Button, Card, Field, Input, Select, Textarea, useToast } from "./ui";

export const GROUPS: { id: CheckGroup; label: string }[] = [
  { id: "outcome", label: "Outcome" }, { id: "responsiveness", label: "Responsiveness" }, { id: "knowledge", label: "Knowledge" },
  { id: "tools", label: "Tools" }, { id: "memory", label: "Memory" }, { id: "safety", label: "Safety" },
];
export const VERDICT: Record<Verdict, { label: string; tone: Tone }> = {
  pass: { label: "Pass", tone: "ok" }, fail: { label: "Fail", tone: "bad" }, "n/a": { label: "N/A", tone: "neutral" },
  unknown: { label: "Unknown", tone: "warn" }, not_judged: { label: "Not judged", tone: "neutral" },
};
export const SOURCE: Record<ScoreCheck["source"], string> = { built_in: "Built-in", config: "From your policy", custom: "Custom" };

export const VerdictBadge = ({ v }: { v: Verdict }) => <Badge tone={VERDICT[v]?.tone ?? "neutral"}>{VERDICT[v]?.label ?? v}</Badge>;

const REVIEWER_KEY = "reviewer";
function savedReviewer(): string {
  try { return localStorage.getItem(REVIEWER_KEY) ?? ""; } catch { return ""; }
}

/** UI-48: the call's scorecard - hard-fail banner, measures, grouped checks with evidence, reviews and rescore. */
export function ScorecardCard({ card, events, onEvidence, onRescore, onChange }: {
  card: Scorecard | null; events: CallEvent[]; onEvidence: (seq: number) => void; onRescore: () => Promise<void>; onChange: () => void;
}) {
  const [rescoring, setRescoring] = useState(false);
  const toast = useToast();
  const rescore = async () => {
    setRescoring(true);
    try { await onRescore(); toast("Scoring queued", "ok"); } catch (e) { toast((e as ApiError).detail, "bad"); } finally { setRescoring(false); }
  };
  const action = <Button variant="ghost" onClick={rescore} loading={rescoring}>Rescore</Button>;
  if (!card) return <Card title="Scorecard" actions={action}><div className="text-sm text-muted">Not scored yet.</div></Card>;
  const m = card.measures;
  const failedGates = card.checks.filter((c) => c.hard_gate && c.verdict === "fail");
  const chunks = new Map<string, string>();
  for (const e of events) for (const r of e.data?.result?.results ?? []) if (r.chunk_id) chunks.set(r.chunk_id, `${r.title} › ${r.heading}`);
  return (
    <Card title="Scorecard" actions={<>{card.score != null && <Badge tone="accent">Score {pct(card.score)}</Badge>}{action}</>}>
      <div className="space-y-4 text-sm">
        {failedGates.length > 0 && (
          <div role="alert" className="rounded-lg bg-bad-soft px-3 py-2 text-bad">
            <div className="font-semibold">Hard fail</div>
            <ul className="mt-0.5 list-disc pl-5">{failedGates.map((c) => <li key={c.key}>{c.text}</li>)}</ul>
          </div>
        )}
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
          <div><dt className="text-muted">First response</dt><dd>{secs(m.first_response_ms)}</dd></div>
          <div><dt className="text-muted">Response p50 / p95</dt><dd>{secs(m.latency_p50_ms)} / {secs(m.latency_p95_ms)}</dd></div>
          <div><dt className="text-muted">Tool calls (errors)</dt><dd>{m.tool_calls ?? 0} ({m.tool_errors ?? 0})</dd></div>
          <div><dt className="text-muted">Knowledge searches (no answer)</dt><dd>{m.knowledge_searches ?? 0} ({m.no_answer_searches ?? 0})</dd></div>
        </dl>
        {!card.judged && <p className="text-xs text-muted">The judge did not score this call (sampling); only the code checks are decided.</p>}
        {GROUPS.map((g) => {
          const checks = card.checks.filter((c) => c.group === g.id);
          if (!checks.length) return null;
          return (
            <div key={g.id}>
              <div className="text-xs font-medium text-muted">{g.label}</div>
              <ul className="mt-1 space-y-1.5">
                {checks.map((c) => (
                  <CheckRow key={c.key} check={c} scorecardId={card.id} review={card.reviews[c.key]} chunks={chunks} onEvidence={onEvidence} onChange={onChange} />
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function CheckRow({ check: c, scorecardId, review, chunks, onEvidence, onChange }: {
  check: ScoreCheck; scorecardId: string; review?: Scorecard["reviews"][string]; chunks: Map<string, string>;
  onEvidence: (seq: number) => void; onChange: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [verdict, setVerdict] = useState<"pass" | "fail" | "n/a">("pass");
  const [note, setNote] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  useEffect(() => { setReviewer(savedReviewer()); }, []);
  const send = async (v: "pass" | "fail" | "n/a", n = "") => {
    const name = reviewer.trim() || savedReviewer() || "Reviewer";
    setBusy(true);
    try {
      await api(`/api/scorecards/${scorecardId}/reviews/${encodeURIComponent(c.key)}`, { method: "PUT", json: { verdict: v, note: n || null, reviewer: name } });
      try { localStorage.setItem(REVIEWER_KEY, name); } catch { /* storage unavailable */ }
      setOpen(false);
      onChange();
    } catch (e) {
      toast((e as ApiError).detail, "bad");
    } finally {
      setBusy(false);
    }
  };
  const agreeable = c.verdict === "pass" || c.verdict === "fail" || c.verdict === "n/a";
  return (
    <li className="rounded-lg border border-line px-2.5 py-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <VerdictBadge v={c.verdict} />
        <Badge tone={c.method === "code" ? "info" : "neutral"}>{c.method === "code" ? "Code" : "Judge"}</Badge>
        {c.hard_gate && <Badge tone="warn">Hard gate</Badge>}
        {review && <span className="ml-auto text-xs">Reviewer: <VerdictBadge v={review.verdict} /> <span className="text-muted">{review.reviewer}</span></span>}
      </div>
      <div className="mt-1">{c.text}</div>
      {c.reason && <div className="mt-0.5 text-xs text-muted">{c.reason}</div>}
      {(c.evidence.seqs.length > 0 || c.evidence.chunk_ids.length > 0) && (
        <div className="mt-1 flex flex-wrap gap-2 text-xs">
          {c.evidence.seqs.map((s) => <button key={s} className="text-accent hover:underline" onClick={() => onEvidence(s)}>Turn {s}</button>)}
          {c.evidence.chunk_ids.map((id) => <span key={id} className="text-muted">{chunks.get(id) ?? `Chunk ${id.slice(0, 8)}`}</span>)}
        </div>
      )}
      {review?.note && <div className="mt-1 rounded bg-neutral-soft px-2 py-1 text-xs">{review.note}</div>}
      {c.method === "judge" && c.verdict !== "not_judged" && (
        <div className="mt-1.5 flex gap-1.5">
          <Button variant="ghost" className="min-h-8 px-3 py-1 text-xs" disabled={busy || !agreeable}
            onClick={() => agreeable && send(c.verdict as "pass" | "fail" | "n/a")}>Agree</Button>
          <Button variant="ghost" className="min-h-8 px-3 py-1 text-xs" disabled={busy} onClick={() => setOpen(!open)}>Disagree</Button>
        </div>
      )}
      {open && (
        <div className="mt-2 grid gap-2 rounded-lg bg-neutral-soft p-2 sm:grid-cols-2">
          <Field label="Correct verdict">
            <Select value={verdict} onChange={(e) => setVerdict(e.target.value as "pass" | "fail" | "n/a")}>
              <option value="pass">Pass</option><option value="fail">Fail</option><option value="n/a">N/A</option>
            </Select>
          </Field>
          <Field label="Your name"><Input value={reviewer} onChange={(e) => setReviewer(e.target.value)} maxLength={120} /></Field>
          <div className="sm:col-span-2"><Field label="Note (optional)"><Textarea maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} /></Field></div>
          <div className="sm:col-span-2 flex justify-end"><Button variant="primary" loading={busy} onClick={() => send(verdict, note)}>Save review</Button></div>
        </div>
      )}
    </li>
  );
}
