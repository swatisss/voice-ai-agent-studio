// Spec: /ui/agent-builder.md (Knowledge tab), /architecture/knowledge.md (Website sources)
"use client";

import { ChevronDown, ChevronRight, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { useTenant } from "@/components/shell";
import { Badge, Button, Field, Input, Modal, Select, useToast } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { ago } from "@/lib/format";

type Source = {
  id: string; title: string; start_url: string; scope: "page" | "section"; max_pages: number; refresh: "off" | "daily" | "weekly";
  status: "indexing" | "ready" | "partial" | "failed"; page_count: number; found_count: number; last_synced_at: string | null;
  error: string | null; last_run: { skipped?: { url: string; reason: string }[] };
};
type Props = { draft: any; update: (path: string[], v: unknown) => void; adding: boolean; onAdded: () => void; onClose: () => void };

function statusBadge(s: Source) {
  if (s.status === "indexing") return <Badge tone="warn">Indexing… {s.page_count}{s.found_count ? ` of ${s.found_count}` : ""} pages</Badge>;
  if (s.status === "failed") return <Badge tone="bad">Failed{s.error ? `: ${s.error}` : ""}</Badge>;
  if (s.status === "partial") return <Badge tone="info">Partial: {s.page_count} of {s.found_count} pages</Badge>;
  return <Badge tone="ok">Ready · {s.page_count} {s.page_count === 1 ? "page" : "pages"}</Badge>;
}

/** Website sources of the tenant: rows with status, Sync now and their pages; the From URL dialog (UI-66). */
export function WebsiteSources({ draft, update, adding, onAdded, onClose }: Props) {
  const { tenant } = useTenant();
  const toast = useToast();
  const { data, reload } = useApi<{ items: Source[] }>("/api/knowledge/sources", [tenant]);
  const [form, setForm] = useState({ url: "", scope: "section", max_pages: 25, refresh: "daily" });
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<Record<string, any>>({});
  const ids: string[] = draft.knowledge_source_ids ?? [];
  const indexing = (data?.items ?? []).some((s) => s.status === "indexing");

  useEffect(() => {  // the page count rises while a source indexes
    if (!indexing) return;
    const t = setInterval(reload, 2000);
    return () => clearInterval(t);
  }, [indexing, reload]);

  async function add() {
    setBusy(true);
    try {
      const src = await api<Source>("/api/knowledge/sources", { method: "POST", json: {
        start_url: form.url.trim(), scope: form.scope, max_pages: Number(form.max_pages), refresh: form.refresh } });
      update(["knowledge_source_ids"], [...ids, src.id]);  // ticked for this agent at once
      setForm({ url: "", scope: "section", max_pages: 25, refresh: "daily" });
      onAdded();
      reload();
    } catch (e) { toast((e as ApiError).detail, "bad"); } finally { setBusy(false); }
  }

  async function sync(id: string) {
    try {
      await api(`/api/knowledge/sources/${id}/sync`, { method: "POST" });
      reload();
    } catch (e) { toast((e as ApiError).detail, "bad"); }
  }

  async function expand(id: string) {
    if (open[id]) { setOpen({ ...open, [id]: undefined }); return; }
    setOpen({ ...open, [id]: await api(`/api/knowledge/sources/${id}`) });
  }

  return (
    <>
      {!!data?.items.length && (
        <ul className="mb-2 divide-y divide-line border-b border-line">
          {data.items.map((s) => (
            <li key={s.id} className="py-2 text-sm">
              <div className="flex items-center gap-3">
                <input type="checkbox" aria-label={`Use ${s.title}`} checked={ids.includes(s.id)}
                  onChange={() => update(["knowledge_source_ids"], ids.includes(s.id) ? ids.filter((i) => i !== s.id) : [...ids, s.id])} />
                <button className="flex items-center gap-1 text-left" onClick={() => expand(s.id)} aria-expanded={!!open[s.id]}>
                  {open[s.id] ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  <span className="font-medium">{s.title}</span>
                </button>
                <span className="min-w-0 flex-1 truncate text-xs text-muted">{s.start_url}</span>
                {statusBadge(s)}
                {s.last_synced_at && s.status !== "indexing" && <span className="text-xs text-muted">synced {ago(s.last_synced_at)} ago</span>}
                <Button variant="ghost" onClick={() => sync(s.id)} disabled={s.status === "indexing"} aria-label="Sync now"><RefreshCw size={14} />Sync now</Button>
              </div>
              {open[s.id] && (
                <ul className="ml-8 mt-2 space-y-1 text-xs">
                  {open[s.id].pages.filter((p: any) => p.status === "active").map((p: any) => (
                    <li key={p.doc_id} className="flex gap-2"><a className="text-accent underline" href={p.url} target="_blank" rel="noreferrer">{p.title}</a>
                      <span className="text-muted">{p.chunk_count} chunks</span></li>
                  ))}
                  {(s.last_run?.skipped ?? []).map((k) => <li key={k.url} className="text-muted">Skipped {k.url}: {k.reason}</li>)}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
      <Modal open={adding} title="Add from URL" onClose={onClose}
        footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} disabled={!form.url.trim()} onClick={add}>Add</Button></>}>
        <Field label="URL"><Input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://…" /></Field>
        <Field label="What to index">
          <Select value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })}>
            <option value="page">Just this page</option><option value="section">This site section</option>
          </Select>
        </Field>
        {form.scope === "section" && (
          <Field label="Up to N pages" hint="At most 100. Pages under the same address are followed; robots.txt is respected.">
            <Input type="number" min={1} max={100} value={form.max_pages} onChange={(e) => setForm({ ...form, max_pages: Number(e.target.value) })} />
          </Field>
        )}
        <Field label="Keep in sync" hint="The agent answers from the latest synced pages without a new version.">
          <Select value={form.refresh} onChange={(e) => setForm({ ...form, refresh: e.target.value })}>
            <option value="off">Off</option><option value="daily">Daily</option><option value="weekly">Weekly</option>
          </Select>
        </Field>
      </Modal>
    </>
  );
}
