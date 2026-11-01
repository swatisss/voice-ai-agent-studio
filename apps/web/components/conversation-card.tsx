// Spec: /ui/calls.md (Conversation card), /architecture/agent-transfer.md, /architecture/supervisor-routing.md (Routing record)
"use client";

import Link from "next/link";
import { Badge, Card, Spinner } from "@/components/ui";
import { useApi } from "@/lib/api";
import { label, outcomeTone } from "@/lib/format";

const SOURCE: Record<string, string> = { api: "API", playground: "Playground", phone: "Phone" };

export function ConversationCard({ conversationId, callId, meta, tenant }: { conversationId: string; callId: string; meta: any; tenant: string }) {
  const { data } = useApi<any>(`/api/conversations/${conversationId}`, [tenant, conversationId]);
  if (!data) return <Card title="Conversation"><Spinner /></Card>;
  const routing = meta?.routing;
  const handoff = meta?.handoff;
  return (
    <Card title="Conversation" actions={<Badge tone="info">{SOURCE[data.source] ?? data.source}</Badge>}>
      <ol className="space-y-1 text-sm">
        {data.segments.map((s: any) => (
          <li key={s.call_id} className="flex flex-wrap items-center gap-2">
            <span className="text-muted">{s.segment}.</span>
            {s.call_id === callId ? <span className="font-medium">{s.agent_name}</span> : <Link className="text-accent" href={`/calls/detail/?id=${s.call_id}`}>{s.agent_name}</Link>}
            <span className="text-xs text-muted">{s.routed_by === "transfer" ? "transferred" : s.routed_by}</span>
            {s.outcome && <Badge tone={outcomeTone(s.outcome)}>{label(s.outcome)}</Badge>}
          </li>
        ))}
      </ol>
      {routing && (
        <p className="mt-3 text-sm"><span className="text-muted">Routed: </span>{label(routing.method)}{routing.confidence != null && ` · ${Number(routing.confidence).toFixed(2)}`}</p>
      )}
      {handoff?.reason && (
        <div className="mt-2 space-y-1 text-sm">
          <div><span className="text-muted">Transfer reason: </span>{handoff.reason}</div>
          {handoff.summary && <div className="rounded-lg bg-neutral-soft p-2">{handoff.summary}</div>}
        </div>
      )}
    </Card>
  );
}
