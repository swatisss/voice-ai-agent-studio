// Spec: /ui/agent-desk.md (Patterns)
"use client";

import Link from "next/link";
import { ClusterLabel } from "@/components/cluster-label";
import { useTenant } from "@/components/shell";
import { Card, EmptyState, Spinner } from "@/components/ui";
import { useApi, useEvents } from "@/lib/api";
import { ROOT_CAUSE, when } from "@/lib/format";

/** What keeps reaching a person, grouped: the call-centre view of the learning loop's clusters. */
export default function PatternsPage() {
  const { tenant } = useTenant();
  const { data, reload } = useApi<{ items: any[] }>("/api/insights/clusters", [tenant]);
  useEvents(["insights"], (e) => { if (e.type.startsWith("cluster")) reload(); }, tenant);
  if (!data) return <Spinner />;
  const items = data.items.filter((c) => c.status !== "ignored");
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Patterns</h1>
        <p className="text-sm text-muted">The questions that keep reaching a person. Tell the agent what you say: it learns from what you write.</p>
      </div>
      {!items.length ? <EmptyState title="No patterns yet">They appear when several escalated calls are about the same thing.</EmptyState> : (
        <div className="grid gap-3 md:grid-cols-2">
          {items.map((c) => (
            <Link key={c.id} href={`/patterns/cluster/?id=${c.id}`} className="block">
              <Card className="h-full hover:border-accent">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="font-semibold">{c.name}</h2><ClusterLabel c={c} />
                </div>
                <p className="mt-1 text-sm text-muted">{c.description}</p>
                <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
                  <span>{c.call_count} calls · {c.escalation_count} escalated</span>
                  <span>{ROOT_CAUSE[c.root_cause] ?? c.root_cause}</span>
                  {c.last_seen_at && <span>Last seen {when(c.last_seen_at)}</span>}
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
