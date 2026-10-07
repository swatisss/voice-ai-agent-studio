// Spec: /ui/calls.md (Detail)
"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { PacketCard } from "@/components/packet";
import { useTenant } from "@/components/shell";
import { Transcript } from "@/components/transcript";
import { Badge, Card, Spinner } from "@/components/ui";
import { useApi } from "@/lib/api";
import { label, maskRef, MODE_LABEL, MODE_TONE, money, outcomeTone, ROOT_CAUSE, secs, when } from "@/lib/format";

export default function Page() {
  return <Suspense fallback={<Spinner />}><CallDetail /></Suspense>;
}

function CallDetail() {
  const id = useSearchParams().get("id") ?? "";
  const { tenant } = useTenant();
  const { data: c, error } = useApi<any>(id ? `/api/calls/${id}` : null, [tenant]);
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
        <Badge tone={MODE_TONE[c.direction] ?? "neutral"}>{MODE_LABEL[c.direction] ?? "Inbound"}</Badge>
        {c.agent_version && <Badge tone="ok">v{c.agent_version}</Badge>}
      </div>
      <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-6">
        <div><div className="text-xs text-muted">Started</div>{when(c.started_at)}</div>
        <div><div className="text-xs text-muted">Duration</div>{duration ? secs(duration) : "—"}</div>
        <div><div className="text-xs text-muted">End reason</div>{label(c.end_reason)}</div>
        <div><div className="text-xs text-muted">Caller</div><span className="mono">{maskRef(c.caller_ref)}</span></div>
        <div><div className="text-xs text-muted">LLM cost</div>{money(c.llm_cost_usd, 4)}</div>
        <div><div className="text-xs text-muted">Tokens</div>{c.tokens_in + c.tokens_out}</div>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" title="Transcript"><Transcript events={c.events} /></Card>
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
