// Spec: /ui/calls.md (Explorer)
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useTenant } from "@/components/shell";
import { Badge, Card, EmptyState, Select, Spinner } from "@/components/ui";
import { useApi } from "@/lib/api";
import { label, maskRef, MODE_LABEL, MODE_TONE, money, outcomeTone, ROOT_CAUSE, when } from "@/lib/format";

export default function CallsPage() {
  const { tenant } = useTenant();
  const router = useRouter();
  const [agent, setAgent] = useState("");
  const [outcome, setOutcome] = useState("");
  const [channel, setChannel] = useState("");
  const [direction, setDirection] = useState("");
  const [seed, setSeed] = useState(true);
  const qs = new URLSearchParams({ include_seed: String(seed), ...(agent && { agent_id: agent }), ...(outcome && { outcome }), ...(channel && { channel }), ...(direction && { direction }) });
  const { data: agents } = useApi<{ items: any[] }>("/api/agents", [tenant]);
  const { data } = useApi<{ items: any[] }>(`/api/calls?${qs}`, [tenant]);
  const versionOf = (c: any) => (c.agent_version ? `v${c.agent_version}` : "");

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Calls</h1>
      <div className="flex flex-wrap items-center gap-2">
        <Select className="w-56" value={agent} onChange={(e) => setAgent(e.target.value)}><option value="">All agents</option>{agents?.items.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select>
        <Select className="w-40" value={outcome} onChange={(e) => setOutcome(e.target.value)}><option value="">All outcomes</option><option value="resolved">Resolved</option><option value="escalated">Escalated</option><option value="abandoned">Abandoned</option></Select>
        <Select className="w-36" value={channel} onChange={(e) => setChannel(e.target.value)}><option value="">All channels</option><option value="voice">Voice</option><option value="text">Text</option></Select>
        <Select className="w-36" value={direction} onChange={(e) => setDirection(e.target.value)}><option value="">All directions</option><option value="inbound">Inbound</option><option value="outbound">Outbound</option><option value="internal">Internal</option></Select>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={seed} onChange={(e) => setSeed(e.target.checked)} />Include seeded history</label>
      </div>
      {!data ? <Spinner /> : !data.items.length ? <EmptyState title="No calls match">Run a test call or change the filters.</EmptyState> : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted"><tr><th className="pb-2">Started</th><th>Channel</th><th>Direction</th><th>Version</th><th>Caller</th><th>Intent</th><th>Outcome</th><th>Root cause</th><th>Turns</th><th>LLM cost</th></tr></thead>
              <tbody>
                {data.items.map((c) => (
                  <tr key={c.id} className="cursor-pointer border-t border-line hover:bg-neutral-soft" onClick={() => router.push(`/calls/detail/?id=${c.id}`)}>
                    <td className="py-2 whitespace-nowrap">{when(c.started_at)}</td>
                    <td>{label(c.channel)}{c.is_seed && <span className="ml-1 text-xs text-muted">(seed)</span>}</td>
                    <td><Badge tone={MODE_TONE[c.direction] ?? "neutral"}>{MODE_LABEL[c.direction] ?? "Inbound"}</Badge></td>
                    <td>{versionOf(c)}</td>
                    <td className="mono text-xs">{maskRef(c.caller_ref)}</td>
                    <td>{label(c.intent)}</td>
                    <td>{c.outcome ? <Badge tone={outcomeTone(c.outcome)}>{label(c.outcome)}</Badge> : <Badge>{label(c.status)}</Badge>}</td>
                    <td>{c.root_cause && c.root_cause !== "none" ? ROOT_CAUSE[c.root_cause] : ""}</td>
                    <td>{c.turn_count}</td>
                    <td>{money(c.llm_cost_usd, 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
