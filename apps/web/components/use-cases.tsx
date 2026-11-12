// Spec: /ui/agent-builder.md (Use cases tab), /architecture/capability-catalog.md
"use client";

import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, Field, Input, Modal, Spinner, Textarea } from "@/components/ui";
import { api, ApiError, useApi, useEvents } from "@/lib/api";
import { ago } from "@/lib/format";

type UseCase = { id: string; title: string; summary: string; category: string; channels: string[]; sample_utterances: string[] };
type Profile = { status: "ready" | "indexing" | "failed"; built_at: string; error: string | null; summary: string; generated_examples: string[] };
type Form = { id?: string; title: string; summary: string; category: string; channels: string[]; samples: string };

const CHANNELS = ["voice", "chat", "phone"];

export function UseCasesTab({ agentId, tenant, published }: { agentId: string; tenant: string; published: boolean }) {
  const { data, reload } = useApi<{ items: UseCase[] }>(`/api/use-cases?agent_id=${agentId}`, [tenant, agentId]);
  const { data: profile, error: profileError, reload: reloadProfile } = useApi<Profile>(published ? `/api/agents/${agentId}/capability` : null, [tenant, agentId]);
  const [form, setForm] = useState<Form | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<UseCase | null>(null);
  const [pending, setPending] = useState(false);

  useEvents(["evaluation"], (e) => {
    if (e.type === "catalog.updated" && e.data.agent_id === agentId) {
      setPending(false);
      reloadProfile();
    }
  }, tenant);

  async function save() {
    if (!form) return;
    setError(null);
    const body = {
      title: form.title, summary: form.summary, category: form.category, channels: form.channels,
      sample_utterances: form.samples.split("\n").map((x) => x.trim()).filter(Boolean),
    };
    try {
      if (form.id) await api(`/api/use-cases/${form.id}`, { method: "PUT", json: body });
      else await api("/api/use-cases", { method: "POST", json: { ...body, agent_id: agentId } });
      setForm(null);
      setPending(published);
      reload();
    } catch (e) {
      setError((e as ApiError).detail);
    }
  }

  async function remove(u: UseCase) {
    await api(`/api/use-cases/${u.id}`, { method: "DELETE" });
    setDeleting(null);
    setPending(published);
    reload();
  }

  const status = pending ? "indexing" : profile?.status;
  return (
    <div className="space-y-4">
      <Card title="Use cases" actions={<Button adminOnly onClick={() => setForm({ title: "", summary: "", category: "", channels: ["voice", "chat"], samples: "" })}><Plus size={14} />Add use case</Button>}>
        <p className="mb-3 text-sm text-muted">Use cases update routing right away; they are not part of a version.</p>
        {!data ? <Spinner /> : data.items.length === 0 ? <p className="text-sm text-muted">No use cases yet. Add the requests this agent handles so callers can be routed to it.</p> : (
          <ul className="divide-y divide-[var(--border)]">
            {data.items.map((u) => (
              <li key={u.id} className="flex items-start gap-3 py-3">
                <div className="flex-1">
                  <div className="font-medium">{u.title}</div>
                  {u.summary && <div className="text-sm text-muted">{u.summary}</div>}
                  <div className="mt-1 flex flex-wrap gap-1">{u.sample_utterances.map((x) => <Badge key={x} tone="info">{x}</Badge>)}</div>
                </div>
                <Button adminOnly variant="ghost" aria-label={`Edit ${u.title}`} onClick={() => setForm({ id: u.id, title: u.title, summary: u.summary, category: u.category, channels: u.channels, samples: u.sample_utterances.join("\n") })}><Pencil size={14} /></Button>
                <Button adminOnly variant="ghost" aria-label={`Delete ${u.title}`} onClick={() => setDeleting(u)}><Trash2 size={14} /></Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title="Routing profile">
        {!published ? <p className="text-sm text-muted">Publish the agent to give it a routing profile.</p>
          : profileError ? <p className="text-sm text-muted">Callers are not routed to this agent (routing is switched off, or it places outbound calls).</p>
          : !profile ? <Spinner /> : (
            <div className="space-y-2 text-sm">
              <p>
                {status === "indexing" ? <Badge tone="warn">Updating…</Badge> : status === "failed" ? <Badge tone="bad">Failed</Badge> : <Badge tone="ok">Up to date</Badge>}
                <span className="ml-2 text-muted">built {ago(profile.built_at)}</span>
              </p>
              {profile.error && <p className="text-bad">{profile.error}</p>}
              <p className="text-muted">{profile.summary}</p>
              {profile.generated_examples.length > 0 && (
                <details>
                  <summary className="cursor-pointer font-medium">Generated example requests ({profile.generated_examples.length})</summary>
                  <ul className="mt-2 list-disc pl-5 text-muted">{profile.generated_examples.map((x) => <li key={x}>{x}</li>)}</ul>
                </details>
              )}
            </div>
          )}
      </Card>
      <Modal open={!!form} title={form?.id ? "Edit use case" : "Add use case"} onClose={() => setForm(null)}
        footer={<><Button variant="ghost" onClick={() => setForm(null)}>Cancel</Button><Button variant="primary" onClick={save}>Save</Button></>}>
        {form && (
          <div className="space-y-3">
            <Field label="Title"><Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
            <Field label="Summary"><Textarea value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} /></Field>
            <Field label="Category"><Input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} /></Field>
            <fieldset className="flex gap-4 text-sm">
              <legend className="mb-1 font-medium">Channels</legend>
              {CHANNELS.map((c) => (
                <label key={c} className="flex items-center gap-1">
                  <input type="checkbox" className="accent-[var(--accent)]" checked={form.channels.includes(c)}
                    onChange={(e) => setForm({ ...form, channels: e.target.checked ? [...form.channels, c] : form.channels.filter((x) => x !== c) })} />{c}
                </label>
              ))}
            </fieldset>
            <Field label="Sample phrases" hint="One per line, 1 to 20." error={error}>
              <Textarea value={form.samples} onChange={(e) => setForm({ ...form, samples: e.target.value })} placeholder={"I lost my insurance card\nCan I get a new member card?"} />
            </Field>
          </div>
        )}
      </Modal>
      <Modal open={!!deleting} title="Delete use case?" onClose={() => setDeleting(null)}
        footer={<><Button variant="ghost" onClick={() => setDeleting(null)}>Cancel</Button><Button variant="danger" onClick={() => deleting && remove(deleting)}>Delete</Button></>}>
        <p className="text-sm">Callers asking about <b>{deleting?.title}</b> may no longer be routed to this agent.</p>
      </Modal>
    </div>
  );
}
