// Spec: /ui/settings.md (Front desk), /architecture/supervisor-routing.md (Front desk settings)
"use client";

import { useEffect, useState } from "react";
import { Button, Card, Field, Input, Select, Spinner, useToast } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";

type FrontDesk = {
  persona_id: string | null; pipeline: "cascade" | "realtime"; default_agents: { member: string | null; staff: string | null };
  min_confidence: number | null; max_clarifications: number; connecting_message: string; min_routing_accuracy: number;
  routing_mode: "embedding" | "decision_model"; clear_win: number; clear_margin: number;
};
type DecisionModelHealth = { configured: boolean; hosted: boolean; blocked: boolean };

export function FrontDeskCard({ tenant, allowRealtime }: { tenant: string; allowRealtime: boolean }) {
  const toast = useToast();
  const { data, setData } = useApi<FrontDesk>("/api/tenant-settings/front-desk", [tenant]);
  const { data: personas } = useApi<{ items: { id: string; name: string }[] }>("/api/personas", [tenant]);
  const { data: agents } = useApi<{ items: { id: string; name: string; mode: string; published_version: unknown }[] }>("/api/agents", [tenant]);
  const { data: health } = useApi<{ router?: { decision_model: DecisionModelHealth } }>("/healthz", [tenant]);
  const [form, setForm] = useState<FrontDesk | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (data) setForm(data); }, [data]);

  if (!form) return <Card title="Front desk"><Spinner /></Card>;
  const of = (mode: string) => (agents?.items ?? []).filter((a) => a.published_version && a.mode === mode);
  const dm = health?.router?.decision_model;
  const dmStatus = !dm ? null : dm.blocked ? "blocked by PHI mode" : dm.configured ? "configured" : "not configured";
  const dmNote = !dm ? undefined : dm.blocked ? "Blocked by PHI mode" : !dm.configured ? "Not configured on this server" : undefined;

  async function save() {
    if (!form) return;
    setSaving(true);
    setError(null);
    try {
      setData(await api<FrontDesk>("/api/tenant-settings/front-desk", { method: "PUT", json: form }));
      toast("Front desk saved", "ok");
    } catch (e) {
      setError((e as ApiError).detail);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card title="Front desk" actions={<Button variant="primary" loading={saving} onClick={save}>Save</Button>}>
      <p className="mb-1 max-w-3xl text-sm text-muted">How routed conversations open: the front desk greets the caller, and the supervisor picks the agent.</p>
      {dmStatus && <p className="mb-3 text-xs text-muted">Decision model: {dmStatus}</p>}
      <div className="grid max-w-3xl gap-4 md:grid-cols-2">
        <Field label="Persona">
          <Select value={form.persona_id ?? ""} onChange={(e) => setForm({ ...form, persona_id: e.target.value || null })}>
            {(personas?.items ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </Field>
        <Field label="Voice pipeline">
          <Select value={form.pipeline} onChange={(e) => setForm({ ...form, pipeline: e.target.value as FrontDesk["pipeline"] })}>
            <option value="cascade">Cascade</option>
            {allowRealtime && <option value="realtime">Realtime speech-to-speech</option>}
          </Select>
        </Field>
        <Field label="Default agent for members">
          <Select value={form.default_agents.member ?? ""} onChange={(e) => setForm({ ...form, default_agents: { ...form.default_agents, member: e.target.value || null } })}>
            <option value="">None</option>
            {of("inbound").map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </Select>
        </Field>
        <Field label="Default agent for staff">
          <Select value={form.default_agents.staff ?? ""} onChange={(e) => setForm({ ...form, default_agents: { ...form.default_agents, staff: e.target.value || null } })}>
            <option value="">None</option>
            {of("internal").map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </Select>
        </Field>
        <Field label="Ask a clarifying question">
          <Select value={form.max_clarifications} onChange={(e) => setForm({ ...form, max_clarifications: Number(e.target.value) })}>
            <option value={0}>Never</option><option value={1}>Once</option><option value={2}>Up to twice</option>
          </Select>
        </Field>
        <Field label="Confidence needed" hint={form.min_confidence == null ? "Using the model's default" : form.min_confidence.toFixed(2)}>
          <div className="flex items-center gap-3">
            <input type="range" min={0.3} max={0.95} step={0.05} disabled={form.min_confidence == null} value={form.min_confidence ?? 0.6}
              onChange={(e) => setForm({ ...form, min_confidence: Number(e.target.value) })} className="flex-1 accent-[var(--accent)]" aria-label="Confidence needed" />
            <label className="flex items-center gap-1 text-xs">
              <input type="checkbox" className="accent-[var(--accent)]" checked={form.min_confidence == null}
                onChange={(e) => setForm({ ...form, min_confidence: e.target.checked ? null : 0.6 })} />Use the model&apos;s default
            </label>
          </div>
        </Field>
        <Field label="Connecting message"><Input maxLength={120} value={form.connecting_message} onChange={(e) => setForm({ ...form, connecting_message: e.target.value })} /></Field>
        <Field label="Routing" hint={form.routing_mode === "decision_model" ? dmNote : undefined}>
          <Select value={form.routing_mode} onChange={(e) => setForm({ ...form, routing_mode: e.target.value as FrontDesk["routing_mode"] })}>
            <option value="embedding">Embedding (default)</option>
            <option value="decision_model">Decision model{dmNote ? ` (${dmNote.toLowerCase()})` : ""}</option>
          </Select>
        </Field>
        <Field label="Stage A clear win" hint={`${form.clear_win.toFixed(2)} · Higher: more requests go to the decision model`}>
          <input type="range" min={0.5} max={0.99} step={0.01} value={form.clear_win} aria-label="Stage A clear win"
            onChange={(e) => setForm({ ...form, clear_win: Number(e.target.value) })} className="w-full accent-[var(--accent)]" />
        </Field>
        <Field label="Stage A margin" hint={`${form.clear_margin.toFixed(2)} · Higher: more requests go to the decision model`}>
          <input type="range" min={0} max={0.5} step={0.01} value={form.clear_margin} aria-label="Stage A margin"
            onChange={(e) => setForm({ ...form, clear_margin: Number(e.target.value) })} className="w-full accent-[var(--accent)]" />
        </Field>
        <Field label="Routing suite pass mark (%)" error={error}>
          <Input type="number" min={50} max={100} value={Math.round(form.min_routing_accuracy * 100)} onChange={(e) => setForm({ ...form, min_routing_accuracy: Number(e.target.value) / 100 })} />
        </Field>
      </div>
    </Card>
  );
}
