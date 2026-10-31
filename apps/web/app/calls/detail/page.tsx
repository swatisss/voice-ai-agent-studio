// Spec: /ui/calls.md (Detail), /architecture/call-scoring.md
"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { FeedbackBadge } from "@/components/feedback";
import { PacketCard } from "@/components/packet";
import { ScorecardCard } from "@/components/scorecard";
import { useTenant } from "@/components/shell";
import { Transcript } from "@/components/transcript";
import { Badge, Card, Spinner } from "@/components/ui";
import { api, type MemoryEvent, type MemoryItem, useApi, useEvents } from "@/lib/api";
import { label, maskRef, MODE_LABEL, MODE_TONE, money, outcomeTone, ROOT_CAUSE, secs, when } from "@/lib/format";

export default function Page() {
  return <Suspense fallback={<Spinner />}><CallDetail /></Suspense>;
}

function CallDetail() {
  const id = useSearchParams().get("id") ?? "";
  const { tenant } = useTenant();
  const { data: c, error, reload } = useApi<any>(id ? `/api/calls/${id}` : null, [tenant]);
  const [seq, setSeq] = useState<number | null>(null);
  useEvents(["evaluation"], (e) => { if (e.type === "scorecard.updated" && e.data?.call_id === id) reload(); }, tenant);  // UI-48
  const showTurn = (n: number) => {  // UI-48: evidence links scroll to and highlight the cited line
    setSeq(n);
    requestAnimationFrame(() => document.getElementById(`seq-${n}`)?.scrollIntoView({ block: "center", behavior: "smooth" }));
  };
  useEffect(() => {  // UI-44: "#seq-<n>" opens the transcript at that turn
    if (!c) return;
    const m = /^#seq-(\d+)$/.exec(window.location.hash);
    if (!m) return;
    setSeq(Number(m[1]));
    requestAnimationFrame(() => document.getElementById(`seq-${m[1]}`)?.scrollIntoView({ block: "center" }));
  }, [c]);
  if (error) return <div className="text-sm text-bad">{error.detail}</div>;
  if (!c) return <Spinner />;
  const duration = c.ended_at ? (new Date(c.ended_at).getTime() - new Date(c.started_at).getTime()) : null;
  const a = c.analysis;
  const e = c.escalation;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">Call <span className="mono text-base">{c.id.slice(0, 8)}</span></h1>
        {c.outcome ? <Badge tone={outcomeTone(c.outcome)}>{label(c.outcome)}</Badge> : <Badge>{label(c.status)}</Badge>}
        <Badge>{label(c.channel)}</Badge>
        {c.channel === "simulation" && <Badge tone="info">Simulated</Badge>}
        {c.transport === "phone" && <Badge tone="info">Phone</Badge>}
        <Badge tone={MODE_TONE[c.direction] ?? "neutral"}>{MODE_LABEL[c.direction] ?? "Inbound"}</Badge>
        {c.agent_version && <Badge tone="ok">v{c.agent_version}</Badge>}
        <FeedbackBadge rating={c.feedback?.rating} />
        {c.identification && (
          <Badge tone="info">Identified by caller ID{c.identification.attestation ? ` · ${c.identification.attestation}` : ""}</Badge>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-6 lg:grid-cols-8">
        <div><div className="text-xs text-muted">Started</div>{when(c.started_at)}</div>
        <div><div className="text-xs text-muted">Duration</div>{duration ? secs(duration) : "—"}</div>
        <div><div className="text-xs text-muted">End reason</div>{label(c.end_reason)}</div>
        <div><div className="text-xs text-muted">Caller</div><span className="mono">{maskRef(c.caller_ref)}</span></div>
        {c.telephony && <div><div className="text-xs text-muted">Dialled number</div><span className="mono">{c.telephony.to}</span></div>}
        {c.telephony && <div><div className="text-xs text-muted">Caller phone</div><span className="mono">•••• {c.telephony.from_last4}</span></div>}
        <div><div className="text-xs text-muted">LLM cost</div>{money(c.llm_cost_usd, 4)}</div>
        <div><div className="text-xs text-muted">Tokens</div>{c.tokens_in + c.tokens_out}</div>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" title="Transcript"><Transcript events={c.events} highlightSeq={seq} /></Card>
        <div className="space-y-4">
          {e && (
            <Card title="Escalation" actions={<Badge tone={e.status === "resolved" ? "ok" : "warn"}>{label(e.status)}</Badge>}>
              <PacketCard esc={e} />
              {e.disposition && (
                <div className="mt-3 space-y-1 text-sm">
                  <div><span className="text-muted">Disposition: </span>{label(e.disposition)}{e.assignee && <span className="text-muted"> · {e.assignee}</span>}</div>
                  <div className="rounded-lg bg-neutral-soft p-2">{e.resolution_note}</div>
                </div>
              )}
            </Card>
          )}
          {c.memory && <MemoryCard memory={c.memory} memberHref={c.caller_ref ? `/members/memory/?ref=${encodeURIComponent(c.caller_ref)}&agent=${encodeURIComponent(c.agent_id)}` : null} />}
          {c.feedback && (  // UI-36
            <Card title="Caller feedback" actions={<FeedbackBadge rating={c.feedback.rating} />}>
              <div className="text-sm">{c.feedback.comment ? <p className="rounded-lg bg-neutral-soft p-2">{c.feedback.comment}</p> : <span className="text-muted">No comment.</span>}</div>
              <div className="mt-2 text-xs text-muted">{when(c.feedback.at)}</div>
            </Card>
          )}
          <ScorecardCard card={c.scorecard} events={c.events} onEvidence={showTurn} onChange={reload}
            onRescore={c.channel === "simulation" ? undefined : async () => { await api(`/api/calls/${id}/rescore`, { method: "POST" }); }} />
          {a && (
            <Card title="Analysis">
              <dl className="space-y-1.5 text-sm">
                <div><dt className="text-xs text-muted">Intent</dt><dd>{label(a.intent)}</dd></div>
                <div><dt className="text-xs text-muted">Root cause</dt><dd>{ROOT_CAUSE[a.root_cause] ?? a.root_cause} {a.fixable && <Badge tone="accent">fixable</Badge>}</dd></div>
                {a.gap_summary && <div><dt className="text-xs text-muted">Gap</dt><dd>{a.gap_summary}</dd></div>}
                <div><dt className="text-xs text-muted">Caller goal</dt><dd>{a.caller_goal}</dd></div>
                {a.resolution_summary && <div><dt className="text-xs text-muted">Resolution</dt><dd>{a.resolution_summary}</dd></div>}
                <div><dt className="text-xs text-muted">Sentiment</dt><dd>{a.sentiment_start} → {a.sentiment_end}</dd></div>
                {a.cluster_id && <div><Link className="text-accent" href={`/insights/cluster/?id=${a.cluster_id}`}>Open cluster</Link></div>}
              </dl>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

const sourceHref = (m: MemoryItem) => (m.source_call_id ? `/calls/detail/?id=${m.source_call_id}${m.source_seq != null ? `#seq-${m.source_seq}` : ""}` : null);

/** UI-46: what the agent was given at verification and what it changed after the call. */
function MemoryCard({ memory, memberHref }: { memory: { used: MemoryItem[]; updated: MemoryEvent[] }; memberHref: string | null }) {
  return (
    <Card title="Memory" actions={memberHref && <Link className="text-sm font-medium text-accent" href={memberHref}>Member memory</Link>}>
      <div className="space-y-4 text-sm">
        <div>
          <div className="text-xs font-medium text-muted">Memory used</div>
          {memory.used.length ? (
            <ul className="mt-1 space-y-1.5">
              {memory.used.map((m) => {
                const href = sourceHref(m);
                return (
                  <li key={m.id} className="rounded-lg border border-line px-2.5 py-1.5">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge tone={m.kind === "fact" ? "accent" : "neutral"}>{m.kind === "fact" ? label(m.category) : "Earlier call"}</Badge>
                      {href && <Link className="ml-auto text-xs text-accent" href={href}>Source</Link>}
                    </div>
                    <div className="mt-1">{m.text}</div>
                  </li>
                );
              })}
            </ul>
          ) : <div className="mt-1 text-muted">Nothing was remembered before this call.</div>}
        </div>
        <div>
          <div className="text-xs font-medium text-muted">Memory updated</div>
          {memory.updated.length ? (
            <ul className="mt-1 space-y-1.5">
              {memory.updated.map((e) => (
                <li key={e.id} className="rounded-lg border border-line px-2.5 py-1.5">
                  <Badge tone={e.action === "superseded" ? "warn" : e.action === "added" ? "ok" : "neutral"}>{label(e.action)}</Badge>
                  {e.action === "superseded" ? (
                    <div className="mt-1"><span className="text-muted line-through">{e.text_before}</span> → {e.text_after}</div>
                  ) : (e.text_after ?? e.text_before) && <div className="mt-1">{e.text_after ?? e.text_before}</div>}
                  {e.reason && <div className="mt-1 text-xs text-muted">{e.reason}</div>}
                </li>
              ))}
            </ul>
          ) : <div className="mt-1 text-muted">Nothing new to remember</div>}
        </div>
      </div>
    </Card>
  );
}
