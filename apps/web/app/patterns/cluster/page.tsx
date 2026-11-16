// Spec: /ui/agent-desk.md (Patterns)
"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { ClusterLabel } from "@/components/cluster-label";
import { ClusterComments } from "@/components/comments";
import { useTenant } from "@/components/shell";
import { Card, Spinner } from "@/components/ui";
import { useApi } from "@/lib/api";
import { ROOT_CAUSE, when } from "@/lib/format";

export default function Page() {
  return <Suspense fallback={<Spinner />}><PatternDetail /></Suspense>;
}

function PatternDetail() {
  const id = useSearchParams().get("id") ?? "";
  const { tenant } = useTenant();
  const { data: c, error } = useApi<any>(id ? `/api/insights/clusters/${id}` : null, [tenant]);
  if (error) return <div className="text-sm text-bad">{error.detail}</div>;
  if (!c) return <Spinner />;
  return (
    <div className="space-y-4">
      <Link href="/patterns/" className="text-sm text-accent">&larr; Patterns</Link>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">{c.name}</h1><ClusterLabel c={c} />
      </div>
      <p className="text-sm text-muted">{c.description} · {ROOT_CAUSE[c.root_cause] ?? c.root_cause}</p>
      <Card title={`What people told callers (${c.calls.length} escalated calls)`}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted"><tr><th className="pb-2">Date</th><th>Caller goal</th><th>Resolution note</th><th /></tr></thead>
            <tbody>{c.calls.map((e: any) => (
              <tr key={e.call_id} className="border-t border-line align-top">
                <td className="py-2 whitespace-nowrap">{when(e.date)}</td><td>{e.caller_goal}</td>
                <td>{e.resolution_note || <span className="text-muted">Not resolved yet</span>}</td>
                <td><Link className="text-accent" href={`/calls/detail/?id=${e.call_id}`}>Call</Link></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </Card>
      <ClusterComments clusterId={id} tenant={tenant} />
    </div>
  );
}
