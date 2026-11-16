// Spec: /ui/agent-desk.md (Agents)
"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { useTenant } from "@/components/shell";
import { Badge, Card, EmptyState, Spinner } from "@/components/ui";
import { useApi } from "@/lib/api";
import { MODE_LABEL, MODE_TONE, when } from "@/lib/format";

export default function Page() {
  return <Suspense fallback={<Spinner />}><View /></Suspense>;
}

function View() {
  const id = useSearchParams().get("id");
  return id ? <AgentSetup id={id} /> : <AgentList />;
}

function ReadOnly() {
  return <Badge tone="info">Read-only</Badge>;
}

function AgentList() {
  const { tenant } = useTenant();
  const { data } = useApi<{ items: any[] }>("/api/agents", [tenant]);
  if (!data) return <Spinner />;
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2"><h1 className="text-xl font-semibold">Agents</h1><ReadOnly /></div>
      {!data.items.length ? <EmptyState title="No agents" /> : (
        <div className="grid gap-3 md:grid-cols-2">
          {data.items.map((a) => (
            <Link key={a.id} href={`/agents/view/?id=${a.id}`} className="block">
              <Card className="h-full hover:border-accent">
                <div className="flex items-center gap-2"><h2 className="font-semibold">{a.name}</h2><Badge tone={MODE_TONE[a.mode] ?? "neutral"}>{MODE_LABEL[a.mode] ?? a.mode}</Badge></div>
                <p className="mt-1 text-sm text-muted">{a.description}</p>
                <div className="mt-2 text-xs text-muted">{a.published_version ? `Live: v${a.published_version.version}` : "Not published"}</div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

const List = ({ items }: { items?: string[] }) =>
  items?.length ? <ul className="list-disc space-y-1 pl-5 text-sm">{items.map((x, i) => <li key={i}>{x}</li>)}</ul> : <p className="text-sm text-muted">None.</p>;

function AgentSetup({ id }: { id: string }) {
  const { tenant } = useTenant();
  const { data: a, error } = useApi<any>(`/api/agents/${id}`, [tenant]);
  const { data: versions } = useApi<{ items: any[] }>(`/api/agents/${id}/versions`, [tenant]);
  const { data: docs } = useApi<{ items: any[] }>("/api/knowledge", [tenant]);
  if (error) return <div className="text-sm text-bad">{error.detail}</div>;
  if (!a) return <Spinner />;
  const cfg = a.draft_config ?? {};  // for the Agent Desk the API returns the published setup here
  const policy = cfg.policy ?? {};
  const named = (docs?.items ?? []).filter((d) => (cfg.knowledge_doc_ids ?? []).includes(d.id)).map((d) => d.title);
  return (
    <div className="space-y-4">
      <Link href="/agents/view/" className="text-sm text-accent">&larr; Agents</Link>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">{a.name}</h1><ReadOnly />
        {a.published_version ? <Badge tone="ok">Live: v{a.published_version.version}</Badge> : <Badge>Not published</Badge>}
      </div>
      <p className="text-sm text-muted">Read-only. Ask an admin to change an agent.</p>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Persona">
          <p className="text-sm"><span className="font-medium">{cfg.persona?.name}</span> · {cfg.persona?.tone ?? cfg.persona?.style ?? ""}</p>
          <p className="mt-2 whitespace-pre-wrap text-sm">{cfg.persona?.instructions ?? cfg.persona?.system_prompt ?? ""}</p>
        </Card>
        <Card title="Hand-off to a person">
          <div className="space-y-3 text-sm">
            <div><div className="text-xs font-medium text-muted">Escalate when</div><List items={policy.escalate_when} /></div>
            <div><div className="text-xs font-medium text-muted">Says when handing over</div><p>{policy.handoff_message}</p></div>
          </div>
        </Card>
        <Card title="Always">
          <List items={policy.rules} />
        </Card>
        <Card title="Never">
          <List items={policy.never} />
        </Card>
        <Card title="Tools and skills">
          <div className="space-y-3 text-sm">
            <div><div className="text-xs font-medium text-muted">Tools</div><List items={(cfg.tools ?? []).map((t: any) => `${t.name}: ${t.description}`)} /></div>
            <div><div className="text-xs font-medium text-muted">Skills</div><List items={(cfg.skills ?? []).map((s: any) => `${s.name}: ${s.description ?? ""}`)} /></div>
          </div>
        </Card>
        <Card title="Knowledge"><List items={named} /></Card>
      </div>
      <Card title="Versions">
        {!versions?.items.length ? <p className="text-sm text-muted">No versions yet.</p> : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted"><tr><th className="pb-2">Version</th><th>Date</th><th>Published by</th><th>Note</th></tr></thead>
            <tbody>{versions.items.map((v) => (
              <tr key={v.id} className="border-t border-line"><td className="py-2">v{v.version}</td><td>{when(v.created_at)}</td><td>{v.published_by ?? "—"}</td><td>{v.change_note}</td></tr>
            ))}</tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
