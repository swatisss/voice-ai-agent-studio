// Spec: /ui/agent-desk.md (Knowledge)
"use client";

import { Search } from "lucide-react";
import { useState } from "react";
import { useTenant } from "@/components/shell";
import { Badge, Button, Card, EmptyState, Input, Spinner } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { label, when } from "@/lib/format";

type Doc = { id: string; title: string; source_type: string; status: string; created_at: string };

/** Read-only: the unit's articles and a search, for checking what the agent can say. */
export default function KnowledgePage() {
  const { tenant } = useTenant();
  const { data } = useApi<{ items: Doc[] }>("/api/knowledge", [tenant]);
  const [open, setOpen] = useState<any>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<any[] | null>(null);

  async function show(id: string) { setOpen(await api(`/api/knowledge/${id}`)); }
  async function search() {
    if (!query.trim()) { setHits(null); return; }
    const r = await api<any>("/api/knowledge/search", { method: "POST", json: { query } });
    setHits(r.results ?? r.items ?? []);
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">Knowledge</h1><Badge tone="info">Read-only</Badge>
      </div>
      <p className="text-sm text-muted">What the agents can say. To add or change an article, ask an admin.</p>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); search(); }} role="search">
        <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search the articles" aria-label="Search the articles" />
        <Button type="submit"><Search size={14} />Search</Button>
      </form>
      {hits && (
        <Card title={`${hits.length} matching passages`}>
          {!hits.length ? <p className="text-sm text-muted">Nothing found: the agent would not be able to answer this.</p> : (
            <ul className="space-y-2 text-sm">
              {hits.map((h, i) => <li key={i} className="rounded-lg border border-line p-2"><div className="font-medium">{h.title ?? h.doc_title}</div><p className="text-muted">{h.text ?? h.content}</p></li>)}
            </ul>
          )}
        </Card>
      )}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-2">
          {!data ? <Spinner /> : !data.items.length ? <EmptyState title="No articles" /> : data.items.map((d) => (
            <button key={d.id} onClick={() => show(d.id)} className="block w-full rounded-xl border border-line bg-panel p-3 text-left hover:border-accent">
              <div className="text-sm font-medium">{d.title}</div>
              <div className="mt-0.5 text-xs text-muted">{label(d.source_type)} · {when(d.created_at)}</div>
            </button>
          ))}
        </div>
        <div className="lg:col-span-2">
          {!open ? <EmptyState title="Select an article" /> : (
            <Card title={open.title}><div className="whitespace-pre-wrap text-sm">{open.content}</div></Card>
          )}
        </div>
      </div>
    </div>
  );
}
