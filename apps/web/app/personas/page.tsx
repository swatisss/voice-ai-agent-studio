// Spec: /ui/personas.md
"use client";

import { Pencil, Plus, Trash2, UserRound } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useTenant } from "@/components/shell";
import { Badge, Button, EmptyState, Field, Input, Modal, Select, Spinner, Textarea, useToast } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { VOICES, voiceLabel } from "@/lib/voices";

const BLANK = {
  name: "", description: "", voice: "aura-2-thalia-en", speed: 1.0, greeting: "", disclosure: "I'm a virtual assistant, and this call may be recorded for quality.",
  opening: "", style: "Warm, calm and concise. One question at a time. Plain language.",
};

export default function PersonasPage() {
  const { tenant } = useTenant();
  const toast = useToast();
  const { data, reload } = useApi<{ items: any[] }>("/api/personas", [tenant]);
  const [edit, setEdit] = useState<any>(null);
  const [errors, setErrors] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setErrors(null);
    const { id, used_by, ...body } = edit;
    try {
      await (id ? api(`/api/personas/${id}`, { method: "PUT", json: body }) : api("/api/personas", { method: "POST", json: body }));
      setEdit(null);
      reload();
    } catch (e) {
      setErrors((e as ApiError).detail);
    } finally {
      setSaving(false);
    }
  }

  async function remove(p: any) {
    try {
      await api(`/api/personas/${p.id}`, { method: "DELETE" });
      reload();
    } catch (e) {
      toast((e as ApiError).detail.startsWith("Used by") ? `Can't delete "${p.name}". ${(e as ApiError).detail}` : (e as ApiError).detail, "bad");  // UI-21
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1>Personas</h1>
        <Button variant="primary" onClick={() => { setErrors(null); setEdit({ ...BLANK }); }}><Plus size={16} />New persona</Button>
      </div>
      <p className="max-w-3xl text-muted">A persona is the voice and manner of an agent: name, voice, speaking speed, how it greets, and its style. Agents pick a persona from here, and you can switch personas live during a test call.</p>
      {!data ? <Spinner /> : !data.items.length ? <EmptyState title="No personas yet">Create the voice of your first agent.</EmptyState> : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.items.map((p) => (
            <div key={p.id} className="flex flex-col rounded-2xl border border-line bg-panel p-5 shadow-[var(--shadow)]">
              <div className="flex items-start gap-3">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent"><UserRound size={22} aria-hidden="true" /></span>
                <div className="min-w-0">
                  <div className="text-lg font-semibold">{p.name}</div>
                  <div className="text-sm text-muted">{p.description || "No description"}</div>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap gap-2"><Badge tone="info">{voiceLabel(p.voice)}</Badge><Badge>speed {p.speed}×</Badge></div>
              <blockquote className="mt-3 flex-1 border-l-4 border-accent-soft pl-3 text-sm italic text-muted">“{p.greeting}”</blockquote>
              <div className="mt-3 text-xs text-muted">{p.used_by.length ? `Used by ${p.used_by.join(", ")}` : "Not used by any agent"}</div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button onClick={() => { setErrors(null); setEdit({ ...p }); }}><Pencil size={14} />Edit</Button>
                <Link href={`/test-call/?persona=${p.id}`}><Button variant="ghost">Try in test call</Button></Link>
                <Button variant="ghost" className="ml-auto" onClick={() => remove(p)} aria-label={`Delete ${p.name}`}><Trash2 size={14} /></Button>
              </div>
            </div>
          ))}
        </div>
      )}
      <Modal open={!!edit} title={edit?.id ? `Edit ${edit.name}` : "New persona"} onClose={() => setEdit(null)}
        footer={<><Button onClick={() => setEdit(null)}>Cancel</Button><Button variant="primary" loading={saving} disabled={!edit?.name?.trim() || !edit?.greeting?.trim()} onClick={save}>Save</Button></>}>
        {edit && (
          <div className="max-h-[65vh] space-y-3 overflow-y-auto pr-1">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Name"><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
              <Field label="Voice"><Select value={edit.voice} onChange={(e) => setEdit({ ...edit, voice: e.target.value })}>{VOICES.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}</Select></Field>
            </div>
            <Field label="Description" hint="Shown in lists, for example “Warm and patient, ideal for claims”."><Input value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
            <div>
              <div className="flex items-baseline justify-between"><label htmlFor="speed" className="text-xs font-medium text-muted">Speaking speed</label><span className="text-sm font-semibold text-accent">{Number(edit.speed).toFixed(2)}×</span></div>
              <input id="speed" type="range" className="w-full accent-[var(--accent)]" min={0.7} max={1.5} step={0.05} value={edit.speed} onChange={(e) => setEdit({ ...edit, speed: Number(e.target.value) })} />
            </div>
            <Field label="Greeting (inbound calls)"><Textarea value={edit.greeting} onChange={(e) => setEdit({ ...edit, greeting: e.target.value })} /></Field>
            <Field label="Disclosure" hint="Required: say it is a virtual assistant and the call may be recorded."><Textarea value={edit.disclosure} onChange={(e) => setEdit({ ...edit, disclosure: e.target.value })} /></Field>
            <Field label="Outbound opening" hint="Placeholders: {first_name}"><Textarea value={edit.opening} onChange={(e) => setEdit({ ...edit, opening: e.target.value })} /></Field>
            <Field label="Speaking style" error={errors}><Textarea value={edit.style} onChange={(e) => setEdit({ ...edit, style: e.target.value })} /></Field>
          </div>
        )}
      </Modal>
    </div>
  );
}
