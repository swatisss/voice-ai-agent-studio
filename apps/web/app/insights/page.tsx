// Spec: /ui/insights.md (Cluster list)
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ClusterLabel } from "@/components/cluster-label";
import { useTenant } from "@/components/shell";
import { Badge, Button, EmptyState, Select, Spinner, Stat, useToast } from "@/components/ui";
import { api, ApiError, useApi, useEvents } from "@/lib/api";
import { money, ROOT_CAUSE, when } from "@/lib/format";

export default function InsightsPage() {
  const { tenant } = useTenant();
  const toast = useToast();
  const router = useRouter();
  const [agent, setAgent] = useState("");
  const { data: agents } = useApi<{ items: any[] }>("/api/agents", [tenant]);
  const { data, reload } = useApi<{ items: any[] }>(`/api/insights/clusters${agent ? `?agent_id=${agent}` : ""}`, [tenant]);
  const [drafting, setDrafting] = useState<string | null>(null);
  useEvents(["insights"], (e) => {
    if (e.type === "proposal.updated" && drafting && e.data.cluster_id === drafting) {
      setDrafting(null);
      router.push(`/insights/cluster/?id=${e.data.cluster_id}`);
    }
    if (e.type.startsWith("cluster") || e.type.startsWith("proposal")) reload();
  }, tenant);

  async function draft(id: string) {
    setDrafting(id);
    try { await api(`/api/insights/clusters/${id}/draft-fix`, { method: "POST" }); }
    catch (e) { setDrafting(null); toast((e as ApiError).detail, "bad"); }
  }

  if (!data) return <Spinner />;
  const items = data.items;
  const fixable = items.filter((c) => c.fixable && c.status !== "fixed" && c.status !== "ignored");
  const ready = items.filter((c) => c.ready_for_fix);
  const weeklyFixable = fixable.reduce((s, c) => s + c.weekly_escalations, 0);
  const savings = fixable.reduce((s, c) => s + c.est_weekly_cost_usd, 0);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">Insights</h1>
        <Select className="ml-auto w-60" value={agent} onChange={(e) => setAgent(e.target.value)}><option value="">All agents</option>{agents?.items.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Open clusters" value={items.filter((c) => c.status === "open" || c.status === "fix_proposed").length} />
        <Stat label="Ready for a fix" value={ready.length} />
        <Stat label="Fixable escalations / week" value={weeklyFixable.toFixed(1)} />
        <Stat label="Potential weekly savings" value={money(savings)} />
      </div>
      {!items.length ? <EmptyState title="No clusters yet">Escalated calls are analyzed and grouped here automatically.</EmptyState> : (
        <div className="grid gap-3 md:grid-cols-2">
          {items.map((c) => (
            <div key={c.id} className="rounded-xl border border-line bg-panel p-4">
              <div className="flex items-start justify-between gap-2">
                <Link href={`/insights/cluster/?id=${c.id}`} className="font-medium hover:text-accent">{c.name}</Link>
                <ClusterLabel c={c} />
              </div>
              <p className="mt-1 text-sm text-muted">{c.description}</p>
              <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                <Badge tone={c.fixable ? "accent" : "neutral"}>{ROOT_CAUSE[c.root_cause] ?? c.root_cause}</Badge>
                <span>{c.escalations_28d} escalations (28 d)</span>
                <span>{c.weekly_escalations}/week</span>
                <span className="font-medium">{money(c.est_weekly_cost_usd)}/week</span>
                <span className="text-xs text-muted">last {when(c.last_seen_at)}</span>
              </div>
              {c.ready_for_fix && (
                <div className="mt-3"><Button variant="primary" loading={drafting === c.id} onClick={() => draft(c.id)}>{drafting === c.id ? "Drafting fix…" : "Draft fix"}</Button></div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
