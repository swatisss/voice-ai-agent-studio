// Spec: /ui/test-call.md
"use client";

import { BookOpen, ChevronDown, ChevronRight, Mic, PhoneIncoming, PhoneOff, PhoneOutgoing, Send } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useTenant } from "@/components/shell";
import { ActivityList, Transcript } from "@/components/transcript";
import { Badge, Button, Card, cx, EmptyState, Input, Select, Spinner, Tabs, useToast } from "@/components/ui";
import { api, ApiError, type CallEvent, useApi, useEvents } from "@/lib/api";
import { MODE_LABEL, MODE_TONE, money, secs } from "@/lib/format";
import { VoiceClient } from "@/lib/voice";
import { LiveControlsCard } from "@/components/live-controls";
import { DEFAULT_TURN, type TurnDetection } from "@/lib/voices";

const MODE_ICON: Record<string, typeof PhoneIncoming> = { inbound: PhoneIncoming, outbound: PhoneOutgoing, internal: BookOpen };

type Mode = "talk" | "type";

export default function Page() {
  return <Suspense fallback={<Spinner />}><TestCall /></Suspense>;
}

function TestCall() {
  const { tenant } = useTenant();
  const params = useSearchParams();
  const router = useRouter();
  const toast = useToast();
  const { data: agents } = useApi<{ items: any[] }>("/api/agents", [tenant]);
  const published = (agents?.items ?? []).filter((a) => a.published_version);
  const agentId = params.get("agent") && published.some((a) => a.id === params.get("agent")) ? params.get("agent")! : published[0]?.id ?? "";
  const agent = published.find((a) => a.id === agentId);

  const [mode, setMode] = useState<Mode>("type");
  const [callId, setCallId] = useState<string | null>(null);
  const [events, setEvents] = useState<CallEvent[]>([]);
  const [call, setCall] = useState<any>(null);
  const [status, setStatus] = useState<"idle" | "connecting" | "active" | "ended">("idle");
  const [escalated, setEscalated] = useState(false);
  const [text, setText] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [level, setLevel] = useState(0);
  const [speaking, setSpeaking] = useState(false);
  const [helper, setHelper] = useState(true);
  const [ucId, setUcId] = useState("");
  const [targetRef, setTargetRef] = useState("");
  const { data: useCases } = useApi<{ items: any[] }>("/api/use-cases", [tenant]);
  const outbound = agent?.mode === "outbound";
  const { data: targets } = useApi<{ items: any[] }>(outbound ? `/api/outbound/targets?agent_id=${agentId}` : null, [agentId, outbound]);
  const ucs = useCases?.items ?? [];
  const useCase = ucs.find((u) => u.id === ucId && u.agent_id === agentId) ?? ucs.find((u) => u.agent_id === agentId);
  const target = (targets?.items ?? []).find((t) => t.member_ref === targetRef) ?? targets?.items?.[0];
  const { data: personas } = useApi<{ items: any[] }>("/api/personas", [tenant]);
  const { data: agentDetail } = useApi<any>(agentId ? `/api/agents/${agentId}` : null, [agentId]);
  const [personaId, setPersonaId] = useState(params.get("persona") ?? "");
  const [turn, setTurn] = useState<TurnDetection>(DEFAULT_TURN);
  const voice = useRef<VoiceClient | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const merge = useCallback((incoming: CallEvent[]) => {
    setEvents((prev) => {
      const map = new Map(prev.map((e) => [e.seq, e]));
      for (const e of incoming) map.set(e.seq, e);
      return [...map.values()].sort((a, b) => a.seq - b.seq);
    });
  }, []);

  const sync = useCallback(async (id: string) => {
    const d = await api(`/api/calls/${id}`);
    setCall(d);
    merge(d.events);
    if (d.escalation) setEscalated(true);
    if (d.ended_at) setStatus("ended");
  }, [merge]);

  useEvents(callId ? [`call:${callId}`] : [], (e) => {
    if (e.type === "call.event") merge([e.data]);
    if (e.type === "call.escalated") setEscalated(true);
    if (e.type === "call.ended" && callId) { setStatus("ended"); sync(callId); }
  }, tenant);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [events.length]);
  useEffect(() => {  // the agent's own defaults seed the controls whenever no call is running
    if (agentDetail && !callId) setTurn({ ...DEFAULT_TURN, ...(agentDetail.draft_config?.voice?.turn_detection ?? {}) });
  }, [agentDetail, callId]);
  useEffect(() => () => voice.current?.hangup(), []);

  function reset() {
    voice.current?.hangup();
    voice.current = null;
    setCallId(null); setEvents([]); setCall(null); setStatus("idle"); setEscalated(false); setLevel(0); setSpeaking(false);
  }

  async function start() {
    reset();
    setStatus("connecting");
    try {
      const r = await api("/api/calls", { method: "POST", json: { agent_id: agentId, channel: mode === "talk" ? "voice" : "text", persona_id: personaId || undefined, turn_detection: mode === "talk" ? turn : undefined, context: outbound ? { member_ref: target?.member_ref } : undefined } });
      setCallId(r.call_id);
      if (mode === "type") {
        await sync(r.call_id);
        setStatus("active");
        return;
      }
      const client = new VoiceClient({
        onReady: () => setStatus("active"),
        onLevel: setLevel,
        onSpeaking: setSpeaking,
        onEnd: () => setStatus("ended"),
        onClose: (code) => {
          if (code === 4500) toast("Voice is unavailable (speech provider key missing) — use Type mode", "bad");
          setStatus("ended");
          sync(r.call_id);
        },
      });
      voice.current = client;
      await client.start(r.call_id, tenant);
    } catch (e) {
      setStatus("idle");
      toast(e instanceof ApiError ? e.detail : `Could not start: ${(e as Error).message}`, "bad");
    }
  }

  async function send() {
    if (!callId || !text.trim()) return;
    const msg = text.trim();
    setText("");
    setWaiting(true);
    try {
      const r = await api(`/api/calls/${callId}/messages`, { method: "POST", json: { text: msg } });
      if (r.escalated) setEscalated(true);
      if (r.ended) setStatus("ended");
      await sync(callId);
    } catch (e) {
      toast((e as ApiError).detail, "bad");
    } finally {
      setWaiting(false);
    }
  }

  async function hangup() {
    if (!callId) return;
    if (voice.current) { voice.current.hangup(); voice.current = null; }
    else await api(`/api/calls/${callId}/end`, { method: "POST" }).catch(() => undefined);
    setStatus("ended");
    setTimeout(() => sync(callId), 400);  // UI-09
  }

  if (agents && !published.length) return <EmptyState title="No published agents">Publish an agent in <Link className="text-accent" href="/agents/">Agents</Link> first.</EmptyState>;
  if (!agent) return <Spinner />;
  const outcome = call?.outcome ?? (escalated ? "escalated" : null);
  const busy = status === "active" || status === "connecting";
  const direction: string = call?.direction ?? agent.mode ?? "inbound";
  const startLabel = outbound ? "Place outbound call" : mode === "talk" ? "Start call" : "Start chat";
  const pick = (u: any) => { if (busy) return; reset(); setUcId(u.id); router.replace(`/test-call/?agent=${u.agent_id}`); };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">Test call</h1>
        <Select className="max-w-xs" value={agentId} onChange={(e) => { reset(); router.replace(`/test-call/?agent=${e.target.value}`); }}>
          {published.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </Select>
        <Badge tone="ok">v{agent.published_version.version}</Badge>
        <Badge tone={MODE_TONE[direction] ?? "neutral"}>{MODE_LABEL[direction] ?? direction}</Badge>
        <div className="ml-auto w-56"><Tabs<Mode> value={mode} onChange={(m) => { if (status === "idle" || status === "ended") setMode(m); }} tabs={[{ id: "talk", label: "Talk" }, { id: "type", label: "Type" }]} /></div>
      </div>
      {ucs.length > 0 && (
        <section aria-label="Use cases" className="space-y-2">
          <h2 className="text-sm font-semibold text-muted">{ucs[0].category}</h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {ucs.map((u) => {
              const Icon = MODE_ICON[u.mode] ?? PhoneIncoming;
              const selected = useCase?.id === u.id;
              return (
                <button key={u.id} disabled={busy || !u.published} aria-pressed={selected} onClick={() => pick(u)}
                  className={cx("flex flex-col gap-1.5 rounded-2xl border-[1.5px] bg-panel p-3 text-left transition disabled:opacity-60",
                    selected ? "border-accent bg-accent-soft" : "border-line hover:border-accent")}>
                  <span className="flex items-center gap-2 text-sm font-semibold"><Icon size={16} className="shrink-0 text-accent" />{u.title}</span>
                  <span className="line-clamp-2 text-xs text-muted">{u.summary}</span>
                  <span className="mt-auto flex flex-wrap gap-1 pt-1">
                    <Badge tone={MODE_TONE[u.mode] ?? "neutral"}>{MODE_LABEL[u.mode] ?? u.mode}</Badge>
                    {u.channels.map((c: string) => <Badge key={c}>{c === "chat" ? "Chat" : "Voice"}</Badge>)}
                  </span>
                </button>
              );
            })}
          </div>
          {useCase && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-medium text-muted">Try saying</span>
              {useCase.sample_utterances.map((t: string) => (
                <button key={t} disabled={mode !== "type"} onClick={() => setText(t)} title={mode === "type" ? "Fill the message box" : "Say this in Talk mode"}
                  className="rounded-full border border-line bg-panel px-3 py-1 text-xs hover:border-accent disabled:cursor-default disabled:hover:border-line">“{t}”</button>
              ))}
            </div>
          )}
        </section>
      )}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" title={mode === "talk" ? "Voice call" : "Chat"} actions={
          busy
            ? <Button variant="danger" onClick={hangup}><PhoneOff size={14} />{mode === "talk" ? "Hang up" : "End chat"}</Button>
            : <Button variant="primary" onClick={start} disabled={outbound && !target}>{outbound && <PhoneOutgoing size={14} />}{startLabel}</Button>
        }>
          {outbound && !busy && (
            <div className="mb-3 space-y-1">
              <label className="text-xs font-medium text-muted" htmlFor="outbound-target">Who should the agent call?</label>
              <Select id="outbound-target" value={target?.member_ref ?? ""} onChange={(e) => setTargetRef(e.target.value)}>
                {(targets?.items ?? []).map((t) => <option key={t.member_ref} value={t.member_ref}>{t.first_name} — {t.summary}</option>)}
              </Select>
              {!targets?.items?.length && <div className="text-xs text-muted">No one is due a call right now.</div>}
              <div className="text-xs text-muted">The agent speaks first. Answer as {target?.first_name ?? "the callee"}.</div>
            </div>
          )}
          <div className="flex h-[52vh] flex-col">
            <div className="flex-1 space-y-2 overflow-y-auto pr-1">
              {status === "idle" && !events.length && <div className="pt-10 text-center text-sm text-muted">{outbound ? "Place the call: the agent opens the conversation, then you answer as the callee." : mode === "talk" ? "Start a call and speak into your microphone (a headset works best)." : "Start a chat and type as the caller."}</div>}
              <Transcript events={events} />
              {waiting && <div className="text-sm text-muted">Agent is typing…</div>}
              <div ref={bottom} />
            </div>
            {status === "ended" && (
              <div className={cx("mt-3 rounded-lg px-3 py-2 text-sm", outcome === "escalated" ? "bg-warn-soft text-warn" : outcome === "resolved" ? "bg-ok-soft text-ok" : "bg-neutral-soft")}>
                {outcome === "escalated" ? "Escalated — waiting for a specialist" : outcome === "resolved" ? "Resolved" : "Call ended"}
                <Button variant="ghost" className="ml-3" onClick={start}>Start new call</Button>
              </div>
            )}
            {mode === "type" && status === "active" && (
              <div className="mt-3 flex gap-2">
                <Input value={text} disabled={escalated || waiting} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()}
                  placeholder={escalated ? "Escalated to a specialist — end the chat when done" : "Type as the caller…"} />
                <Button variant="primary" onClick={send} disabled={escalated || waiting || !text.trim()}><Send size={14} /></Button>
              </div>
            )}
            {mode === "talk" && (status === "active" || status === "connecting") && (
              <div className="mt-3 flex items-center justify-center gap-6">
                <div className={cx("flex h-16 w-16 items-center justify-center rounded-full bg-accent text-on-accent", speaking && "speaking")}
                  style={{ transform: `scale(${1 + Math.min(level * 4, 0.35)})` }}><Mic size={26} /></div>
                <div className="text-sm text-muted">{status === "connecting" ? "Connecting…" : speaking ? "Agent speaking" : "Listening"}</div>
              </div>
            )}
          </div>
        </Card>
        <div className="space-y-4">
          <LiveControlsCard callId={callId} active={status === "active"} voiceCall={mode === "talk"} personas={personas?.items ?? []}
            personaId={personaId} onPersona={setPersonaId} turn={turn} onTurn={setTurn} />
          <Card title="Activity"><ActivityList events={events} /></Card>
          <Card title="Call">
            {callId ? (
              <dl className="grid grid-cols-2 gap-y-1 text-sm">
                <dt className="text-muted">Call</dt><dd><Link className="mono text-accent" href={`/calls/detail/?id=${callId}`}>{callId.slice(0, 8)}</Link></dd>
                <dt className="text-muted">Direction</dt><dd><Badge tone={MODE_TONE[direction] ?? "neutral"}>{MODE_LABEL[direction] ?? direction}</Badge></dd>
                <dt className="text-muted">Status</dt><dd>{escalated ? "escalated" : status}</dd>
                <dt className="text-muted">Turns</dt><dd>{call?.turn_count ?? 0}</dd>
                <dt className="text-muted">Tokens</dt><dd>{(call?.tokens_in ?? 0) + (call?.tokens_out ?? 0)}</dd>
                <dt className="text-muted">LLM cost</dt><dd>{money(call?.llm_cost_usd ?? 0, 4)}</dd>
                <dt className="text-muted">Median latency</dt><dd>{secs(call?.latency_p50_ms)}</dd>
              </dl>
            ) : <div className="text-sm text-muted">No call yet.</div>}
          </Card>
          <Card title={<button className="flex items-center gap-1" onClick={() => setHelper(!helper)}>{helper ? <ChevronDown size={14} /> : <ChevronRight size={14} />}Demo callers</button>}>
            {helper && (useCase?.demo_callers?.length ? (
              <ul className="space-y-2 text-xs">
                {useCase.demo_callers.map((p: any) => (
                  <li key={`${p.member_id}-${p.try}`}><span className="font-medium">{p.name}</span> · ID <span className="mono">{p.member_id}</span> · DOB {p.date_of_birth}<div className="text-muted">{p.try}</div></li>
                ))}
              </ul>
            ) : <div className="text-xs text-muted">No caller to verify: you speak as an Evergreen colleague.</div>)}
          </Card>
        </div>
      </div>
    </div>
  );
}
