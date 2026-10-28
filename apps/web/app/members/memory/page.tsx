// Spec: /ui/member-memory.md
"use client";

import { Download, RotateCcw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useTenant } from "@/components/shell";
import { Badge, Button, Card, EmptyState, Modal, Select, Spinner, useToast } from "@/components/ui";
import { api, ApiError, downloadJson, type MemberMemory, type MemoryEvent, type MemoryItem, useApi } from "@/lib/api";
import { label, maskRef, type Tone, when } from "@/lib/format";

const day = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "—");
const ACTOR: Record<MemoryEvent["actor"], string> = { agent: "The agent", studio: "Someone in the Studio", system: "The system" };
const ACTION_TONE: Record<MemoryEvent["action"], Tone> = { added: "ok", superseded: "warn", confirmed: "info", restored: "accent", expired: "neutral", erased: "bad" };
const sourceHref = (m: MemoryItem) => (m.source_call_id ? `/calls/detail/?id=${m.source_call_id}${m.source_seq != null ? `#seq-${m.source_seq}` : ""}` : null);

export default function Page() {
  return <Suspense fallback={<Spinner />}><MemberMemoryPage /></Suspense>;
}

function MemberMemoryPage() {
  const params = useSearchParams();
  const router = useRouter();
  const toast = useToast();
  const { tenant } = useTenant();
  const ref = params.get("ref") ?? "";
  const agentParam = params.get("agent") ?? "";
  const base = `/api/members/${encodeURIComponent(ref)}/memory`;
  const { data, error, reload } = useApi<MemberMemory>(ref ? `${base}${agentParam ? `?agent_id=${encodeURIComponent(agentParam)}` : ""}` : null, [tenant]);
  const [agents, setAgents] = useState<{ id: string; name: string }[]>([]);
  const [firstName, setFirstName] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [erasing, setErasing] = useState(false);
  const [erasedAt, setErasedAt] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {  // keep the agent select and name when the member has been erased (404)
    if (data?.agents?.length) setAgents(data.agents);
    if (data?.first_name) setFirstName(data.first_name);
  }, [data]);

  if (!ref) return <EmptyState title="No member selected">Open a member&apos;s memory from a verified call in <Link className="text-accent" href="/calls/">Calls</Link>.</EmptyState>;
  const notFound = error?.status === 404;
  if (error && !notFound) return <div className="text-sm text-bad">{error.detail}</div>;
  if (!data && !notFound) return <Spinner label="Loading memory…" />;

  const agentId = agentParam || data?.agents?.[0]?.id || agents[0]?.id || "";
  const facts = notFound ? [] : [...(data?.facts ?? [])].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const episodes = notFound ? [] : [...(data?.episodes ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const retired = notFound ? [] : data?.retired ?? [];
  const events = notFound ? [] : [...(data?.events ?? [])].sort((a, b) => a.at.localeCompare(b.at));
  const history: MemoryEvent[] = events.length || !erasedAt ? events
    : [{ id: "erased-local", agent_id: null, member_ref: ref, memory_id: null, action: "erased", actor: "studio", call_id: null, text_before: null, text_after: null, reason: null, at: erasedAt }];
  const empty = !facts.length && !episodes.length && !retired.length;
  const all = [...facts, ...retired];

  async function restore(m: MemoryItem) {
    setBusyId(m.id);
    try {
      await api(`${base}/${m.id}/restore`, { method: "POST" });
      toast("Restored", "ok");
      await reload();
    } catch (e) { toast((e as ApiError).detail, "bad"); } finally { setBusyId(null); }
  }

  async function erase() {  // UI-45
    setErasing(true);
    try {
      await api(`${base}/erase`, { method: "POST" });
      setErasedAt(new Date().toISOString());
      setConfirmOpen(false);
      toast("Member memory erased", "ok");
      await reload();
    } catch (e) { toast((e as ApiError).detail, "bad"); } finally { setErasing(false); }
  }

  async function exportJson() {
    try { await downloadJson(`${base}/export`, "member-memory.json"); } catch (e) { toast((e as ApiError).detail ?? "Export failed", "bad"); }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">Member memory</h1>
        <span className="mono text-sm">{maskRef(ref)}</span>
        {(data?.first_name ?? firstName) && <span className="text-sm text-muted">{data?.first_name ?? firstName}</span>}
        {agents.length > 0 && (
          <Select aria-label="Agent" className="w-auto max-w-xs" value={agentId}
            onChange={(e) => router.replace(`/members/memory/?ref=${encodeURIComponent(ref)}&agent=${encodeURIComponent(e.target.value)}`)}>
            {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </Select>
        )}
        <div className="ml-auto flex gap-2">
          <Button onClick={exportJson} disabled={notFound}><Download size={14} />Export</Button>
          <Button variant="danger" onClick={() => setConfirmOpen(true)} disabled={notFound}><Trash2 size={14} />Erase member</Button>
        </div>
      </div>

      {empty ? <EmptyState title="Nothing remembered about this member." /> : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title={`Facts (${facts.length})`}>
            {facts.length ? (
              <ul className="space-y-2">
                {facts.map((m) => {
                  const href = sourceHref(m);
                  return (
                    <li key={m.id} className="rounded-xl border border-line p-3 text-sm">
                      <div className="flex flex-wrap items-center gap-2"><Badge tone="accent">{label(m.category)}</Badge><span className="text-xs text-muted">learned on {day(m.valid_at ?? m.created_at)} · expires {day(m.expires_at)}</span></div>
                      <div className="mt-1.5">{m.text}</div>
                      {href && <Link className="mt-1.5 inline-block text-xs font-medium text-accent" href={href}>Why the agent knows this</Link>}
                    </li>
                  );
                })}
              </ul>
            ) : <div className="text-sm text-muted">No active facts.</div>}
          </Card>
          <Card title={`Episodes (${episodes.length})`}>
            {episodes.length ? (
              <ul className="space-y-2">
                {episodes.map((m) => (
                  <li key={m.id} className="rounded-xl border border-line p-3 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs text-muted">{when(m.created_at)} · expires {day(m.expires_at)}</span>
                      {m.source_call_id && <Link className="ml-auto text-xs font-medium text-accent" href={`/calls/detail/?id=${m.source_call_id}`}>Open call</Link>}
                    </div>
                    <div className="mt-1.5">{m.text}</div>
                  </li>
                ))}
              </ul>
            ) : <div className="text-sm text-muted">No call summaries.</div>}
          </Card>
          <Card title={`Retired (${retired.length})`} className="lg:col-span-2">
            {retired.length ? (
              <ul className="space-y-2">
                {retired.map((m) => {
                  const next = m.superseded_by ? all.find((x) => x.id === m.superseded_by) : undefined;
                  const ev = events.find((e) => e.action === "superseded" && (e.memory_id === m.id || e.text_before === m.text));
                  const href = sourceHref(m);
                  return (
                    <li key={m.id} className="flex flex-wrap items-start gap-3 rounded-xl border border-line p-3 text-sm">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2"><Badge>{label(m.category)}</Badge><span className="text-xs text-muted">retired {day(m.invalid_at)}</span></div>
                        <div className="mt-1.5 text-muted line-through">{m.text}</div>
                        <div className="mt-1 text-xs">{m.superseded_by ? <>Replaced by: <span className="font-medium">{next?.text ?? ev?.text_after ?? "a newer fact"}</span></> : "Expired"}</div>
                        {ev?.reason && <div className="mt-1 text-xs text-muted">Reason: {ev.reason}</div>}
                        {href && <Link className="mt-1 inline-block text-xs font-medium text-accent" href={href}>Why the agent knew this</Link>}
                      </div>
                      <Button variant="ghost" onClick={() => restore(m)} loading={busyId === m.id}><RotateCcw size={14} />Restore</Button>
                    </li>
                  );
                })}
              </ul>
            ) : <div className="text-sm text-muted">Nothing retired.</div>}
          </Card>
        </div>
      )}

      {history.length > 0 && (
        <Card title="History">
          <ol className="space-y-2">
            {history.map((e) => (
              <li key={e.id} className="flex flex-wrap items-start gap-2 text-sm">
                <span className="w-32 shrink-0 text-xs text-muted">{when(e.at)}</span>
                <Badge tone={ACTION_TONE[e.action] ?? "neutral"}>{label(e.action)}</Badge>
                <span className="text-xs text-muted">{ACTOR[e.actor] ?? e.actor}</span>
                <span className="min-w-0 flex-1">
                  {e.action === "superseded" ? <><span className="text-muted line-through">{e.text_before}</span> → {e.text_after}</> : e.text_after ?? e.text_before}
                  {e.reason && <span className="block text-xs text-muted">{e.reason}</span>}
                </span>
                {e.call_id && <Link className="text-xs text-accent" href={`/calls/detail/?id=${e.call_id}`}>Call</Link>}
              </li>
            ))}
          </ol>
        </Card>
      )}

      <Modal open={confirmOpen} title="Erase member" onClose={() => setConfirmOpen(false)}
        footer={<><Button onClick={() => setConfirmOpen(false)}>Cancel</Button><Button variant="danger" loading={erasing} onClick={erase}>Erase</Button></>}>
        <p className="text-sm">Erase everything every agent remembers about this member? This cannot be undone.</p>
      </Modal>
    </div>
  );
}
