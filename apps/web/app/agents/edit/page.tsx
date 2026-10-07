// Spec: /ui/agent-builder.md
"use client";

import { Eye, Pencil, Plus, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useTenant } from "@/components/shell";
import { Badge, Button, Card, Field, Input, JsonView, Modal, Select, Spinner, Tabs, Textarea, useToast } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { when } from "@/lib/format";
import { DEFAULT_TURN, VOICES, voiceLabel } from "@/lib/voices";
import { TurnDetectionEditor } from "@/components/voice-settings";

type Tab = "overview" | "persona" | "policy" | "voice" | "knowledge" | "tools" | "skills" | "versions";

export default function Page() {
  return <Suspense fallback={<Spinner />}><Builder /></Suspense>;
}

function Builder() {
  const id = useSearchParams().get("id") ?? "";
  const { tenant } = useTenant();
  const toast = useToast();
  const { data: agent, reload, setData } = useApi<any>(id ? `/api/agents/${id}` : null, [tenant]);
  const [tab, setTab] = useState<Tab>("overview");
  const [draft, setDraft] = useState<any>(null);
  const [meta, setMeta] = useState({ name: "", description: "" });
  const [saving, setSaving] = useState(false);
  const [publishOpen, setPublishOpen] = useState(false);
  const [note, setNote] = useState("");
  const [publishError, setPublishError] = useState<string | null>(null);

  useEffect(() => {
    if (agent) {
      setDraft(structuredClone(agent.draft_config));
      setMeta({ name: agent.name, description: agent.description });
    }
  }, [agent]);
  const dirty = useMemo(() => !!agent && !!draft && (JSON.stringify(draft) !== JSON.stringify(agent.draft_config) || meta.name !== agent.name || meta.description !== agent.description), [agent, draft, meta]);
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); } };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  if (!agent || !draft) return <Spinner label="Loading agent…" />;
  const update = (path: string[], value: unknown) => setDraft((d: any) => {
    const next = structuredClone(d);
    let o = next;
    for (const k of path.slice(0, -1)) o = o[k];
    o[path[path.length - 1]] = value;
    return next;
  });

  async function save(): Promise<boolean> {
    setSaving(true);
    try {
      const a = await api(`/api/agents/${id}`, { method: "PUT", json: { ...meta, draft_config: draft } });
      setData(a);
      toast("Draft saved", "ok");
      return true;
    } catch (e) {
      toast((e as ApiError).detail, "bad");
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function publish() {
    setPublishError(null);
    if (dirty && !(await save())) return;
    try {
      const v = await api(`/api/agents/${id}/publish`, { method: "POST", json: { change_note: note } });
      toast(`Published v${v.version}`, "ok");
      setPublishOpen(false);
      setNote("");
      reload();
    } catch (e) {
      setPublishError((e as ApiError).detail);  // UI-05
    }
  }

  return (
    <div className="space-y-4 pb-16">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">{agent.name}</h1>
        {agent.published_version ? <Badge tone="ok">v{agent.published_version.version}</Badge> : <Badge>Not published</Badge>}
        {dirty && <Badge tone="warn">Draft changes</Badge>}
        <div className="ml-auto flex gap-2">
          <Button onClick={save} loading={saving} disabled={!dirty}>Save draft</Button>
          <Button variant="primary" onClick={() => setPublishOpen(true)}>Publish</Button>
          <Link href={`/test-call/?agent=${id}`}><Button disabled={!agent.published_version}>Test call</Button></Link>
        </div>
      </div>
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: "overview", label: "Overview" }, { id: "persona", label: "Persona" }, { id: "policy", label: "Policy" }, { id: "voice", label: "Voice" },
        { id: "knowledge", label: `Knowledge (${draft.knowledge_doc_ids.length})` }, { id: "tools", label: `Tools (${draft.tool_ids.length})` },
        { id: "skills", label: `Skills (${draft.skill_ids.length})` }, { id: "versions", label: "Versions" },
      ]} />
      {tab === "overview" && <Overview draft={draft} meta={meta} setMeta={setMeta} update={update} />}
      {tab === "persona" && <Persona draft={draft} update={update} />}
      {tab === "policy" && <PolicyTab draft={draft} update={update} />}
      {tab === "voice" && <VoiceTab draft={draft} update={update} />}
      {tab === "knowledge" && <KnowledgeTab draft={draft} update={update} />}
      {tab === "tools" && <ToolsTab draft={draft} update={update} />}
      {tab === "skills" && <SkillsTab draft={draft} update={update} />}
      {tab === "versions" && <Versions id={id} />}
      {dirty && (
        <div className="fixed bottom-4 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-full border border-line bg-panel px-4 py-2 shadow-lg">
          <span className="text-sm">Unsaved changes</span>
          <Button variant="primary" onClick={save} loading={saving}>Save draft</Button>
        </div>
      )}
      <Modal open={publishOpen} title="Publish a new version" onClose={() => setPublishOpen(false)}
        footer={<><Button onClick={() => setPublishOpen(false)}>Cancel</Button><Button variant="primary" onClick={publish}>Publish</Button></>}>
        <Field label="Change note"><Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What changed?" /></Field>
        {publishError && <div className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{publishError}</div>}
      </Modal>
    </div>
  );
}

type TabProps = { draft: any; update: (path: string[], v: unknown) => void };

function Overview({ draft, meta, setMeta, update }: TabProps & { meta: { name: string; description: string }; setMeta: (m: any) => void }) {
  const { data: models } = useApi<any>("/api/models");
  return (
    <Card>
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Name"><Input value={meta.name} onChange={(e) => setMeta({ ...meta, name: e.target.value })} /></Field>
        <Field label="Realtime model" hint={models ? `Role default: ${models.roles.realtime}` : undefined}>
          <Select value={draft.models?.realtime ?? ""} onChange={(e) => update(["models", "realtime"], e.target.value || null)}>
            <option value="">Default (role setting)</option>
            {models?.selectable.map((m: string) => <option key={m} value={m}>{m}</option>)}
          </Select>
        </Field>
        <Field label="Call mode" hint="Inbound: customers call in. Outbound: the agent phones people from a target list. Internal: staff ask questions, no member verification.">
          <Select value={draft.mode ?? "inbound"} onChange={(e) => update(["mode"], e.target.value)}>
            <option value="inbound">Inbound</option><option value="outbound">Outbound</option><option value="internal">Internal</option>
          </Select>
        </Field>
        {draft.mode === "outbound" && (
          <Field label="Targets URL" hint="Returns the people to call: {targets: [{member_ref, first_name, summary, context}]}. Required for outbound agents.">
            <Input value={draft.outbound?.targets_url ?? ""} placeholder="/mock/insurance/outreach/renewals" onChange={(e) => update(["outbound", "targets_url"], e.target.value)} />
          </Field>
        )}
        <div className="md:col-span-2"><Field label="Description"><Textarea value={meta.description} onChange={(e) => setMeta({ ...meta, description: e.target.value })} /></Field></div>
      </div>
      <div className="mt-4 flex gap-4 text-sm text-muted">
        <span>{draft.knowledge_doc_ids.length} docs</span><span>{draft.tool_ids.length} tools</span><span>{draft.skill_ids.length} skills</span>
      </div>
    </Card>
  );
}

function Persona({ draft, update }: TabProps) {
  const { tenant } = useTenant();
  const { data } = useApi<{ items: any[] }>("/api/personas", [tenant]);
  const p = draft.persona;
  const chosen = data?.items.find((x) => x.id === draft.persona_id);
  return (
    <div className="space-y-4">
      <Card title="Library persona" actions={<Link className="text-sm font-medium text-accent" href="/personas/">Manage personas</Link>}>
        <Field label="Persona" hint="Personas live in the library so several agents can share a voice. Publishing snapshots the persona into the version.">
          <Select value={draft.persona_id ?? ""} onChange={(e) => update(["persona_id"], e.target.value || null)}>
            <option value="">None: use the inline persona below</option>
            {data?.items.map((x) => <option key={x.id} value={x.id}>{x.name}{x.description ? ` — ${x.description}` : ""}</option>)}
          </Select>
        </Field>
        {chosen && (
          <div className="mt-3 rounded-xl bg-accent-soft p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2"><b>{chosen.name}</b><Badge tone="info">{voiceLabel(chosen.voice)}</Badge><Badge>speed {chosen.speed}×</Badge></div>
            <div className="mt-1 italic text-muted">“{chosen.greeting}”</div>
            <div className="mt-1 text-muted">{chosen.style}</div>
          </div>
        )}
      </Card>
      {!draft.persona_id && (
        <Card title="Inline persona">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Name"><Input value={p.name} onChange={(e) => update(["persona", "name"], e.target.value)} /></Field>
            <Field label="Voice"><Select value={p.voice} onChange={(e) => update(["persona", "voice"], e.target.value)}>{VOICES.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}</Select></Field>
            <Field label={`Speaking speed (${Number(p.speed ?? 1).toFixed(2)}×)`}><input type="range" className="w-full accent-[var(--accent)]" min={0.7} max={1.5} step={0.05} value={p.speed ?? 1} onChange={(e) => update(["persona", "speed"], Number(e.target.value))} /></Field>
            <div />
            <Field label="Greeting"><Textarea value={p.greeting} onChange={(e) => update(["persona", "greeting"], e.target.value)} /></Field>
            <Field label="Disclosure" hint="Required: say it's a virtual assistant and the call may be recorded."><Textarea value={p.disclosure} onChange={(e) => update(["persona", "disclosure"], e.target.value)} /></Field>
            <Field label="Outbound opening" hint="Placeholders: {first_name}"><Textarea value={p.opening ?? ""} onChange={(e) => update(["persona", "opening"], e.target.value)} /></Field>
            <Field label="Speaking style"><Textarea value={p.style} onChange={(e) => update(["persona", "style"], e.target.value)} /></Field>
          </div>
        </Card>
      )}
    </div>
  );
}

function VoiceTab({ draft, update }: TabProps) {
  const value = { ...DEFAULT_TURN, ...(draft.voice?.turn_detection ?? {}) };
  return (
    <Card title="Turn detection">
      <p className="mb-4 max-w-3xl text-sm text-muted">Decide when the agent starts replying. These are the agent's defaults and are versioned when you publish; on the Test call page you can compare modes and change them live during a call.</p>
      <TurnDetectionEditor value={value} onChange={(v) => update(["voice"], { ...(draft.voice ?? {}), turn_detection: v })} />
    </Card>
  );
}

function ListEditor({ label, items, onChange }: { label: string; items: string[]; onChange: (v: string[]) => void }) {
  return (
    <Field label={label}>
      <div className="space-y-1.5">
        {items.map((it, i) => (
          <div key={i} className="flex gap-2">
            <Input value={it} onChange={(e) => onChange(items.map((x, j) => (j === i ? e.target.value : x)))} />
            <Button variant="ghost" onClick={() => onChange(items.filter((_, j) => j !== i))} aria-label="Remove"><Trash2 size={14} /></Button>
          </div>
        ))}
        <Button variant="ghost" onClick={() => onChange([...items, ""])}><Plus size={14} />Add</Button>
      </div>
    </Field>
  );
}

function PolicyTab({ draft, update }: TabProps) {
  const p = draft.policy;
  return (
    <Card>
      <div className="grid gap-5 md:grid-cols-2">
        <ListEditor label="Rules" items={p.rules} onChange={(v) => update(["policy", "rules"], v)} />
        <ListEditor label="Escalate when" items={p.escalate_when} onChange={(v) => update(["policy", "escalate_when"], v)} />
        <ListEditor label="Never" items={p.never} onChange={(v) => update(["policy", "never"], v)} />
        <div className="space-y-3">
          <Field label="Max turns"><Input type="number" min={4} max={40} value={p.max_turns} onChange={(e) => update(["policy", "max_turns"], Number(e.target.value))} /></Field>
          <Field label="Handoff message"><Textarea value={p.handoff_message} onChange={(e) => update(["policy", "handoff_message"], e.target.value)} /></Field>
          <Field label="Holding message"><Textarea value={p.holding_message} onChange={(e) => update(["policy", "holding_message"], e.target.value)} /></Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={p.safety_screen} onChange={(e) => update(["policy", "safety_screen"], e.target.checked)} />Safety screen (emergency and self-harm language)</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={p.voice_filler} onChange={(e) => update(["policy", "voice_filler"], e.target.checked)} />Voice filler before slow lookups</label>
        </div>
      </div>
    </Card>
  );
}

function toggle(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}

function KnowledgeTab({ draft, update }: TabProps) {
  const { tenant } = useTenant();
  const toast = useToast();
  const { data, reload } = useApi<{ items: any[] }>("/api/knowledge", [tenant]);
  const [mode, setMode] = useState<"text" | "url" | null>(null);
  const [form, setForm] = useState({ title: "", content: "", url: "" });
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<any>(null);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<any>(null);

  async function add() {
    setBusy(true);
    try {
      const doc = mode === "url"
        ? await api("/api/knowledge/url", { method: "POST", json: { url: form.url } })
        : await api("/api/knowledge/text", { method: "POST", json: { title: form.title, content: form.content } });
      update(["knowledge_doc_ids"], [...draft.knowledge_doc_ids, doc.id]);
      setMode(null);
      setForm({ title: "", content: "", url: "" });
      reload();
    } catch (e) { toast((e as ApiError).detail, "bad"); } finally { setBusy(false); }
  }

  async function upload(file: File) {
    const fd = new FormData();
    fd.append("file", file);
    setBusy(true);
    try {
      const r = await api<{ items: any[] }>("/api/knowledge/upload", { method: "POST", body: fd });
      update(["knowledge_doc_ids"], [...draft.knowledge_doc_ids, ...r.items.map((d) => d.id)]);
      toast(`Imported ${r.items.length} document(s)`, "ok");  // UI-06
      reload();
    } catch (e) { toast((e as ApiError).detail, "bad"); } finally { setBusy(false); }
  }

  async function test() {
    setResult(await api("/api/knowledge/search", { method: "POST", json: { query, doc_ids: draft.knowledge_doc_ids } }));
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2" title="Documents" actions={<>
        <Button onClick={() => setMode("text")}>Paste text</Button>
        <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-line bg-panel px-3 py-1.5 text-sm font-medium hover:bg-neutral-soft">
          <Upload size={14} />Upload<input type="file" hidden accept=".md,.txt,.pdf,.zip" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        </label>
        <Button onClick={() => setMode("url")}>From URL</Button>
      </>}>
        {busy && <Spinner label="Processing…" />}
        <ul className="divide-y divide-line">
          {data?.items.map((d) => (
            <li key={d.id} className="flex items-center gap-3 py-2 text-sm">
              <input type="checkbox" checked={draft.knowledge_doc_ids.includes(d.id)} onChange={() => update(["knowledge_doc_ids"], toggle(draft.knowledge_doc_ids, d.id))} />
              <span className="flex-1">{d.title}</span>
              <Badge tone={d.source_type === "okf" ? "info" : "neutral"}>{d.source_type === "okf" ? "OKF" : d.source_type}</Badge>
              {d.status === "draft" && <Badge tone="warn">draft</Badge>}
              <span className="text-xs text-muted">{d.chunk_count} chunks</span>
              <Button variant="ghost" onClick={async () => setPreview(await api(`/api/knowledge/${d.id}`))} aria-label="Preview"><Eye size={14} /></Button>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Test search">
        <div className="flex gap-2"><Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="How do I get a Green Card?" onKeyDown={(e) => e.key === "Enter" && test()} /><Button onClick={test}>Search</Button></div>
        {result && (result.no_answer
          ? <div className="mt-3 rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn">No answer — the agent would offer a specialist</div>
          : <ul className="mt-3 space-y-2">{result.results.map((r: any, i: number) => (
              <li key={i} className="rounded-lg border border-line p-2 text-xs"><div className="font-medium">{r.title} › {r.heading} <span className="text-muted">({r.score})</span></div><div className="mt-1 line-clamp-3 text-muted">{r.content}</div></li>
            ))}</ul>)}
      </Card>
      <Modal open={!!mode} title={mode === "url" ? "Add from URL" : "Paste text"} onClose={() => setMode(null)}
        footer={<><Button onClick={() => setMode(null)}>Cancel</Button><Button variant="primary" loading={busy} onClick={add}>Add</Button></>}>
        {mode === "url" ? <Field label="URL"><Input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://…" /></Field> : <>
          <Field label="Title"><Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
          <Field label="Content (Markdown)"><Textarea className="min-h-48" value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} /></Field>
        </>}
      </Modal>
      <Modal open={!!preview} title={preview?.title ?? ""} onClose={() => setPreview(null)}>
        <div className="max-h-[60vh] space-y-2 overflow-auto">
          {preview?.chunks.map((c: any) => <div key={c.ordinal} className="rounded-lg border border-line p-2 text-xs"><div className="font-medium">{c.heading || "(intro)"}</div><div className="mt-1 whitespace-pre-wrap text-muted">{c.content}</div></div>)}
        </div>
      </Modal>
    </div>
  );
}

const EMPTY_TOOL = { name: "", description: "", method: "GET", url: "", parameters: { type: "object", properties: {} }, requires_verification: false, is_verification: false, timeout_s: 8 };

function ToolsTab({ draft, update }: TabProps) {
  const { tenant } = useTenant();
  const toast = useToast();
  const { data, reload } = useApi<{ items: any[] }>("/api/tools", [tenant]);
  const [edit, setEdit] = useState<any>(null);
  const [params, setParams] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const open = (t: any) => { setEdit({ ...t }); setParams(JSON.stringify(t.parameters, null, 2)); setErr(null); };

  async function save() {
    let parsed;
    try { parsed = JSON.parse(params); } catch { setErr("Parameters must be valid JSON"); return; }
    const body = { ...edit, parameters: parsed };
    delete body.id; delete body.status;
    try {
      const t = edit.id ? await api(`/api/tools/${edit.id}`, { method: "PUT", json: body }) : await api("/api/tools", { method: "POST", json: body });
      if (!edit.id) update(["tool_ids"], [...draft.tool_ids, t.id]);
      setEdit(null);
      reload();
    } catch (e) { setErr((e as ApiError).detail); toast("Tool not saved", "bad"); }
  }

  return (
    <Card title="Tools" actions={<Button onClick={() => open(EMPTY_TOOL)}><Plus size={14} />New tool</Button>}>
      <ul className="divide-y divide-line">
        {data?.items.map((t) => (
          <li key={t.id} className="flex items-center gap-3 py-2 text-sm">
            <input type="checkbox" checked={draft.tool_ids.includes(t.id)} onChange={() => update(["tool_ids"], toggle(draft.tool_ids, t.id))} />
            <span className="mono">{t.name}</span>
            <span className="flex-1 truncate text-muted">{t.description}</span>
            {t.is_verification && <Badge tone="info">verifies identity</Badge>}
            {t.requires_verification && <Badge tone="warn">needs verification</Badge>}
            <Badge>{t.method}</Badge>
            <Button variant="ghost" onClick={() => open(t)} aria-label="Edit"><Pencil size={14} /></Button>
          </li>
        ))}
      </ul>
      <Modal open={!!edit} title={edit?.id ? `Edit ${edit.name}` : "New tool"} onClose={() => setEdit(null)}
        footer={<><Button onClick={() => setEdit(null)}>Cancel</Button><Button variant="primary" onClick={save}>Save</Button></>}>
        {edit && <>
          <div className="grid grid-cols-3 gap-2">
            <div className="col-span-2"><Field label="Name (snake_case)"><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field></div>
            <Field label="Method"><Select value={edit.method} onChange={(e) => setEdit({ ...edit, method: e.target.value })}><option>GET</option><option>POST</option></Select></Field>
          </div>
          <Field label="Description"><Textarea value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
          <Field label="URL" hint="Relative URLs call this platform in-process, e.g. /mock/healthcare/claims/{claim_id}"><Input value={edit.url} onChange={(e) => setEdit({ ...edit, url: e.target.value })} /></Field>
          <Field label="Parameters (JSON Schema)" error={err}><Textarea className="mono min-h-40 text-xs" value={params} onChange={(e) => setParams(e.target.value)} /></Field>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-2"><input type="checkbox" checked={edit.requires_verification} onChange={(e) => setEdit({ ...edit, requires_verification: e.target.checked })} />Requires verification</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={edit.is_verification} onChange={(e) => setEdit({ ...edit, is_verification: e.target.checked })} />Is verification tool</label>
            <label className="flex items-center gap-2">Timeout <Input type="number" className="w-16" value={edit.timeout_s} onChange={(e) => setEdit({ ...edit, timeout_s: Number(e.target.value) })} />s</label>
          </div>
        </>}
      </Modal>
    </Card>
  );
}

const EMPTY_SKILL = { name: "", description: "", instructions: "", required_tools: [] as string[], escalate_when: "" };

function SkillsTab({ draft, update }: TabProps) {
  const { tenant } = useTenant();
  const toast = useToast();
  const { data, reload } = useApi<{ items: any[] }>("/api/skills", [tenant]);
  const { data: tools } = useApi<{ items: any[] }>("/api/tools", [tenant]);
  const [edit, setEdit] = useState<any>(null);

  async function save() {
    const body = { ...edit };
    delete body.id; delete body.status;
    try {
      const k = edit.id ? await api(`/api/skills/${edit.id}`, { method: "PUT", json: body }) : await api("/api/skills", { method: "POST", json: body });
      if (!edit.id) update(["skill_ids"], [...draft.skill_ids, k.id]);
      setEdit(null);
      reload();
    } catch (e) { toast((e as ApiError).detail, "bad"); }
  }

  return (
    <Card title="Skills" actions={<Button onClick={() => setEdit({ ...EMPTY_SKILL })}><Plus size={14} />New skill</Button>}>
      <ul className="divide-y divide-line">
        {data?.items.map((k) => (
          <li key={k.id} className="flex items-start gap-3 py-2 text-sm">
            <input className="mt-1" type="checkbox" checked={draft.skill_ids.includes(k.id)} onChange={() => update(["skill_ids"], toggle(draft.skill_ids, k.id))} />
            <div className="flex-1"><div className="font-medium">{k.name}</div><div className="text-muted">{k.description}</div>
              <div className="mt-1 flex flex-wrap gap-1">{k.required_tools.map((t: string) => <Badge key={t} tone="info">{t}</Badge>)}</div></div>
            <Button variant="ghost" onClick={() => setEdit({ ...k })} aria-label="Edit"><Pencil size={14} /></Button>
          </li>
        ))}
      </ul>
      <Modal open={!!edit} title={edit?.id ? `Edit ${edit.name}` : "New skill"} onClose={() => setEdit(null)}
        footer={<><Button onClick={() => setEdit(null)}>Cancel</Button><Button variant="primary" onClick={save}>Save</Button></>}>
        {edit && <>
          <Field label="Name"><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
          <Field label="Use when"><Input value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
          <Field label="Steps"><Textarea className="min-h-32" value={edit.instructions} onChange={(e) => setEdit({ ...edit, instructions: e.target.value })} /></Field>
          <Field label="Required tools">
            <div className="flex flex-wrap gap-2">{tools?.items.map((t) => (
              <label key={t.id} className="flex items-center gap-1 text-xs"><input type="checkbox" checked={edit.required_tools.includes(t.name)} onChange={() => setEdit({ ...edit, required_tools: toggle(edit.required_tools, t.name) })} /><span className="mono">{t.name}</span></label>
            ))}</div>
          </Field>
          <Field label="Escalate when"><Input value={edit.escalate_when} onChange={(e) => setEdit({ ...edit, escalate_when: e.target.value })} /></Field>
        </>}
      </Modal>
    </Card>
  );
}

function Versions({ id }: { id: string }) {
  const { data } = useApi<{ items: any[] }>(`/api/agents/${id}/versions`);
  return (
    <Card title="Versions">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted"><tr><th className="pb-2">Version</th><th>Change note</th><th>Source</th><th>Published</th></tr></thead>
        <tbody>{data?.items.map((v) => (
          <tr key={v.id} className="border-t border-line">
            <td className="py-2"><Badge tone="ok">v{v.version}</Badge></td><td>{v.change_note}</td>
            <td>{v.source_proposal_id ? <Badge tone="accent">Fix proposal</Badge> : <span className="text-muted">Manual</span>}</td><td>{when(v.created_at)}</td>
          </tr>
        ))}</tbody>
      </table>
      {data && <div className="mt-3"><JsonView value={data.items} label="Raw" /></div>}
    </Card>
  );
}
