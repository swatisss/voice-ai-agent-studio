// Spec: /ui/dashboard.md
"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ClusterLabel } from "@/components/cluster-label";
import { useTenant } from "@/components/shell";
import { Badge, Card, EmptyState, Spinner, Stat } from "@/components/ui";
import { useApi, useEvents } from "@/lib/api";
import { money, pct, ROOT_CAUSE, secs, when } from "@/lib/format";

export default function Dashboard() {
  const { tenant } = useTenant();
  const { data, reload } = useApi<any>("/api/dashboard/summary", [tenant]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEvents(["dashboard"], () => {  // UI-04: refetch (debounced) on call.ended / agent.published
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(reload, 2000);
  }, tenant);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  if (!data) return <Spinner label="Loading dashboard…" />;
  const t = data.totals;
  if (!t.calls) return <EmptyState title="No calls yet">Publish an agent and run a test call to see metrics here.</EmptyState>;
  const weekly = data.weekly.map((w: any) => ({ week: w.week_start.slice(5), containment: w.containment_rate == null ? null : Math.round(w.containment_rate * 100), calls: w.calls }));
  const causes = data.by_root_cause.map((c: any) => ({ cause: ROOT_CAUSE[c.root_cause] ?? c.root_cause, count: c.count }));

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Dashboard</h1>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Stat label="Calls" value={t.calls} />
        <Stat label="Containment rate" value={pct(t.containment_rate)} sub="resolved ÷ (resolved + escalated)" />
        <Stat label="Escalated" value={t.escalated} />
        <Stat label="Cost saved" value={money(t.cost_saved_usd)} sub="vs. human-handled" />
        <Stat label="Avg LLM cost / call" value={money(t.avg_llm_cost_usd, 3)} />
        <Stat label="Median response" value={secs(t.latency_p50_ms)} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Containment by week">
          <div className="h-60">
            <ResponsiveContainer>
              <LineChart data={weekly} margin={{ left: -20, right: 10 }}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis dataKey="week" stroke="var(--muted)" fontSize={12} />
                <YAxis domain={[0, 100]} unit="%" stroke="var(--muted)" fontSize={12} />
                <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--border)" }} />
                <Line type="monotone" dataKey="containment" stroke="var(--accent)" strokeWidth={2} dot />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Escalations by root cause">
          <div className="h-60">
            <ResponsiveContainer>
              <BarChart data={causes} layout="vertical" margin={{ left: 40 }}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis type="number" stroke="var(--muted)" fontSize={12} allowDecimals={false} />
                <YAxis type="category" dataKey="cause" stroke="var(--muted)" fontSize={12} width={110} />
                <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--border)" }} />
                <Bar dataKey="count" fill="var(--chart-warn)" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Top clusters" className="lg:col-span-2" actions={<Link className="text-sm text-accent" href="/insights/">Open insights</Link>}>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted"><tr><th className="pb-2">Cluster</th><th>Esc./week</th><th>Est. weekly cost</th><th>Status</th></tr></thead>
            <tbody>
              {data.top_clusters.map((c: any) => (
                <tr key={c.id} className="border-t border-line">
                  <td className="py-2"><Link href={`/insights/cluster/?id=${c.id}`} className="hover:text-accent">{c.name}</Link></td>
                  <td>{c.weekly_escalations}</td>
                  <td>{money(c.est_weekly_cost_usd)}</td>
                  <td><ClusterLabel c={c} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card title="Recent versions">
          <ul className="space-y-2 text-sm">
            {data.recent_versions.map((v: any) => (
              <li key={v.id} className="flex items-start gap-2">
                <Badge tone={v.source_proposal_id ? "accent" : "neutral"}>v{v.version}</Badge>
                <div><div>{v.source_proposal_id ? `From fix: ${v.change_note.replace(/^Fix: /, "")}` : v.change_note}</div><div className="text-xs text-muted">{when(v.created_at)}</div></div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}
