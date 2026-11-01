// Spec: /ui/settings.md (API keys, Webhooks), /api/public-api.md (API keys), /architecture/webhooks.md
"use client";

import { useState } from "react";
import { Badge, Button, Card, Field, Input, Modal, Select, Spinner, useToast } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { ago } from "@/lib/format";

type ApiKey = {
  id: string; name: string; prefix: string; scope: "member" | "staff"; rate_limit_per_min: number; max_concurrent_voice: number;
  created_at: string; last_used_at: string | null; revoked_at: string | null;
};

const SCOPE_LABEL = { member: "Members", staff: "Staff" } as const;

export function ApiKeysCard({ tenant }: { tenant: string }) {
  const toast = useToast();
  const { data, reload } = useApi<{ items: ApiKey[] }>("/api/api-keys", [tenant]);
  const [form, setForm] = useState<{ name: string; scope: "member" | "staff"; rate: string; voice: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);

  async function create() {
    if (!form) return;
    setError(null);
    try {
      const r = await api<ApiKey & { key: string }>("/api/api-keys", {
        method: "POST", json: { name: form.name, scope: form.scope, rate_limit_per_min: Number(form.rate), max_concurrent_voice: Number(form.voice) },
      });
      setForm(null);
      setCreated(r.key);
      reload();
    } catch (e) {
      setError((e as ApiError).detail);
    }
  }

  async function revoke(k: ApiKey) {
    await api(`/api/api-keys/${k.id}`, { method: "DELETE" });
    setRevoking(null);
    toast(`Key ${k.name} revoked`, "ok");
    reload();
  }

  return (
    <Card title="API keys" actions={<Button onClick={() => setForm({ name: "", scope: "member", rate: "120", voice: "10" })}>New key</Button>}>
      <p className="mb-3 max-w-3xl text-sm text-muted">Your systems use a key to start conversations with this unit&apos;s agents through the public API. A key for <b>Members</b> reaches member-facing agents; a key for <b>Staff</b> reaches staff assistants.</p>
      {!data ? <Spinner /> : data.items.length === 0 ? <p className="text-sm text-muted">No keys yet.</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-muted"><tr><th className="py-1 pr-3">Name</th><th className="pr-3">Key</th><th className="pr-3">Scope</th><th className="pr-3">Limits</th><th className="pr-3">Created</th><th className="pr-3">Last used</th><th /></tr></thead>
            <tbody>
              {data.items.map((k) => (
                <tr key={k.id} className="border-t border-[var(--border)]">
                  <td className="py-2 pr-3 font-medium">{k.name}</td>
                  <td className="pr-3 font-mono">{k.prefix}…</td>
                  <td className="pr-3">{SCOPE_LABEL[k.scope]}</td>
                  <td className="pr-3">{k.rate_limit_per_min}/min · {k.max_concurrent_voice} voice</td>
                  <td className="pr-3">{ago(k.created_at)}</td>
                  <td className="pr-3">{k.last_used_at ? ago(k.last_used_at) : "Never"}</td>
                  <td className="text-right">{k.revoked_at ? <Badge tone="neutral">Revoked</Badge> : <Button variant="ghost" onClick={() => setRevoking(k)}>Revoke</Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Modal open={!!form} title="New API key" onClose={() => setForm(null)}
        footer={<><Button variant="ghost" onClick={() => setForm(null)}>Cancel</Button><Button variant="primary" disabled={!form?.name.trim()} onClick={create}>Create key</Button></>}>
        {form && (
          <div className="space-y-3">
            <Field label="Name"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Member app backend" /></Field>
            <Field label="Scope">
              <Select value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value as "member" | "staff" })}>
                <option value="member">Members</option><option value="staff">Staff</option>
              </Select>
            </Field>
            <Field label="Requests per minute"><Input type="number" min={10} max={6000} value={form.rate} onChange={(e) => setForm({ ...form, rate: e.target.value })} /></Field>
            <Field label="Concurrent voice calls" error={error}><Input type="number" min={0} max={200} value={form.voice} onChange={(e) => setForm({ ...form, voice: e.target.value })} /></Field>
          </div>
        )}
      </Modal>
      <Modal open={!!created} title="Your new API key" onClose={() => setCreated(null)} footer={<Button variant="primary" onClick={() => setCreated(null)}>Done</Button>}>
        <p className="mb-2 text-sm font-medium text-bad" role="alert">Copy this key now. It will not be shown again.</p>
        <div className="flex gap-2">
          <Input readOnly value={created ?? ""} className="font-mono" aria-label="New API key" />
          <Button onClick={() => { navigator.clipboard?.writeText(created ?? ""); toast("Key copied", "ok"); }}>Copy</Button>
        </div>
      </Modal>
      <Modal open={!!revoking} title="Revoke key?" onClose={() => setRevoking(null)}
        footer={<><Button variant="ghost" onClick={() => setRevoking(null)}>Cancel</Button><Button variant="danger" onClick={() => revoking && revoke(revoking)}>Revoke</Button></>}>
        <p className="text-sm">Systems using <b>{revoking?.name}</b> stop working at once. This cannot be undone.</p>
      </Modal>
    </Card>
  );
}

type Endpoint = { id: string; url: string; events: string[]; include_transcript: boolean; enabled: boolean; created_at: string; secret_rotated_at: string | null };
type Delivery = { id: string; event_id: string; type: string; status: "pending" | "delivered" | "failed"; attempts: number; last_status_code: number | null; last_error: string | null; created_at: string };

const EVENTS = ["conversation.started", "conversation.transferred", "conversation.escalated", "conversation.ended", "conversation.analyzed"];
const STATUS_TONE = { delivered: "ok", pending: "warn", failed: "bad" } as const;

function Deliveries({ endpoint }: { endpoint: Endpoint }) {
  const { data, reload } = useApi<{ items: Delivery[] }>(`/api/webhooks/${endpoint.id}/deliveries`, [endpoint.id]);
  if (!data) return <Spinner />;
  if (data.items.length === 0) return <p className="text-sm text-muted">No deliveries yet.</p>;
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-muted"><tr><th className="py-1 pr-3">Event</th><th className="pr-3">Status</th><th className="pr-3">Attempts</th><th className="pr-3">Response</th><th className="pr-3">When</th><th /></tr></thead>
      <tbody>
        {data.items.slice(0, 50).map((d) => (
          <tr key={d.id} className="border-t border-[var(--border)]">
            <td className="py-1 pr-3 font-mono">{d.type}</td>
            <td className="pr-3"><Badge tone={STATUS_TONE[d.status]}>{d.status}</Badge></td>
            <td className="pr-3">{d.attempts}</td>
            <td className="pr-3">{d.last_status_code ?? d.last_error ?? "—"}</td>
            <td className="pr-3">{ago(d.created_at)}</td>
            <td className="text-right">{d.status !== "pending" && <Button variant="ghost" onClick={async () => { await api(`/api/webhooks/deliveries/${d.id}/resend`, { method: "POST" }); reload(); }}>Resend</Button>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function WebhooksCard({ tenant }: { tenant: string }) {
  const { data, reload } = useApi<{ items: Endpoint[] }>("/api/webhooks", [tenant]);
  const [form, setForm] = useState<{ url: string; events: string[]; include_transcript: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  async function create() {
    if (!form) return;
    setError(null);
    try {
      const r = await api<Endpoint & { secret: string }>("/api/webhooks", { method: "POST", json: form });
      setForm(null);
      setSecret(r.secret);
      reload();
    } catch (e) {
      const err = e as ApiError;
      setError(err.error === "secrets_unavailable" ? "Secret storage is not configured on this server (TENANT_SECRETS_KEY)." : err.detail);
    }
  }

  async function update(ep: Endpoint, patch: Partial<Endpoint>) {
    await api(`/api/webhooks/${ep.id}`, { method: "PUT", json: patch });
    reload();
  }

  return (
    <Card title="Webhooks" actions={<Button disabled={(data?.items.length ?? 0) >= 5} onClick={() => setForm({ url: "", events: ["conversation.ended"], include_transcript: false })}>Add endpoint</Button>}>
      <p className="mb-3 max-w-3xl text-sm text-muted">We post signed events about conversations your systems started through the public API.</p>
      {!data ? <Spinner /> : data.items.length === 0 ? <p className="text-sm text-muted">No endpoints yet.</p> : (
        <ul className="space-y-3">
          {data.items.map((ep) => (
            <li key={ep.id} className="rounded-lg border border-[var(--border)] p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-sm">{ep.url}</span>
                {!ep.enabled && <Badge tone="neutral">Disabled</Badge>}
                {ep.include_transcript && <Badge tone="warn">Transcripts</Badge>}
                <span className="ml-auto flex gap-1">
                  <Button variant="ghost" onClick={() => update(ep, { enabled: !ep.enabled })}>{ep.enabled ? "Disable" : "Enable"}</Button>
                  <Button variant="ghost" onClick={async () => setSecret((await api<{ secret: string }>(`/api/webhooks/${ep.id}/rotate`, { method: "POST" })).secret)}>Rotate secret</Button>
                  <Button variant="ghost" onClick={async () => { await api(`/api/webhooks/${ep.id}`, { method: "DELETE" }); reload(); }}>Delete</Button>
                  <Button variant="ghost" onClick={() => setOpen(open === ep.id ? null : ep.id)}>{open === ep.id ? "Hide deliveries" : "Deliveries"}</Button>
                </span>
              </div>
              <p className="mt-1 text-xs text-muted">{ep.events.join(" · ")}</p>
              {open === ep.id && <div className="mt-3"><Deliveries endpoint={ep} /></div>}
            </li>
          ))}
        </ul>
      )}
      <Modal open={!!form} title="Add webhook endpoint" onClose={() => setForm(null)}
        footer={<><Button variant="ghost" onClick={() => setForm(null)}>Cancel</Button><Button variant="primary" disabled={!form?.url.trim() || !form?.events.length} onClick={create}>Add</Button></>}>
        {form && (
          <div className="space-y-3">
            <Field label="URL" error={error}><Input value={form.url} placeholder="https://example.com/hooks/voice" onChange={(e) => setForm({ ...form, url: e.target.value })} /></Field>
            <fieldset className="space-y-1 text-sm">
              <legend className="mb-1 font-medium">Events</legend>
              {EVENTS.map((ev) => (
                <label key={ev} className="flex items-center gap-2">
                  <input type="checkbox" checked={form.events.includes(ev)} className="accent-[var(--accent)]"
                    onChange={(e) => setForm({ ...form, events: e.target.checked ? [...form.events, ev] : form.events.filter((x) => x !== ev) })} />
                  <span className="font-mono">{ev}</span>
                </label>
              ))}
            </fieldset>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" role="switch" checked={form.include_transcript} className="accent-[var(--accent)]" onChange={(e) => setForm({ ...form, include_transcript: e.target.checked })} />
              Include transcripts
            </label>
            <p className="text-xs text-muted">Transcripts contain member information.</p>
          </div>
        )}
      </Modal>
      <Modal open={!!secret} title="Signing secret" onClose={() => setSecret(null)} footer={<Button variant="primary" onClick={() => setSecret(null)}>Done</Button>}>
        <p className="mb-2 text-sm font-medium text-bad" role="alert">Copy this secret now. It will not be shown again.</p>
        <Input readOnly value={secret ?? ""} className="font-mono" aria-label="Signing secret" />
      </Modal>
    </Card>
  );
}
