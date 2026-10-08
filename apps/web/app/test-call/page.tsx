// Spec: /ui/test-call.md
"use client";

import { ChevronDown, ChevronRight, Mic, PhoneOff, PhoneOutgoing, Send } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useTenant } from "@/components/shell";
import { ActivityList, Transcript } from "@/components/transcript";
import { Badge, Button, Card, cx, EmptyState, Input, Select, Spinner, useToast } from "@/components/ui";
import { api, ApiError, type CallEvent, useApi, useEvents } from "@/lib/api";
import { MODE_LABEL, MODE_TONE, money, secs } from "@/lib/format";
import { VoiceClient } from "@/lib/voice";
import { FeedbackPrompt } from "@/components/feedback";
import { LiveControlsCard } from "@/components/live-controls";
import { DEFAULT_TURN, type TurnDetection } from "@/lib/voices";

type Mode = "talk" | "type";

const TECH_KEY = "test-call-technical";  // UI-32: remembered per browser, off by default

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
  const [scriptOpen, setScriptOpen] = useState(true);
  const [technical, setTechnicalState] = useState(false);
  const [targetRef, setTargetRef] = useState("");
  const { data: useCases } = useApi<{ items: any[] }>("/api/use-cases", [tenant]);
  const outbound = agent?.mode === "outbound";
  const { data: targets } = useApi<{ items: any[] }>(outbound ? `/api/outbound/targets?agent_id=${agentId}` : null, [agentId, outbound]);
  const agentUcs = (useCases?.items ?? []).filter((u) => u.agent_id === agentId);  // what the selected agent handles (UI-24)
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
  useEffect(() => {  // the Technical details choice survives reloads; the page works without storage
    try { setTechnicalState(localStorage.getItem(TECH_KEY) === "1"); } catch { /* storage unavailable */ }
  }, []);
  const setTechnical = (on: boolean) => {
    setTechnicalState(on);
    try { localStorage.setItem(TECH_KEY, on ? "1" : "0"); } catch { /* storage unavailable */ }
  };

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
        onEnd: () => { setStatus("ended"); setSpeaking(false); setLevel(0); sync(r.call_id); },  // UI-35: the server ended the call
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
  const canFill = mode === "type" && status === "active" && !escalated;  // a starting phrase fills the message box only while a chat runs

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">Test call</h1>
        <Select className="max-w-xs" value={agentId} onChange={(e) => { reset(); router.replace(`/test-call/?agent=${e.target.value}`); }}>
          {published.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </Select>
        <Badge tone="ok">v{agent.published_version.version}</Badge>
        <Badge tone={MODE_TONE[direction] ?? "neutral"}>{MODE_LABEL[direction] ?? direction}</Badge>
        <label className="ml-auto flex cursor-pointer items-center gap-2 text-sm text-muted">  {/* UI-32 */}
          <input type="checkbox" role="switch" aria-label="Technical details" className="h-4 w-4 accent-[var(--accent)]" checked={technical} onChange={(e) => setTechnical(e.target.checked)} />
          Technical details
        </label>
      </div>
      {agentUcs.length > 0 && (
        <p className="text-sm text-muted"><span className="font-medium text-fg">Handles:</span> {agentUcs.map((u) => u.title).join(" · ")}</p>
      )}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" title={
          <div className="flex gap-1" role="group" aria-label="Call type">  {/* UI-31: Talk | Type lives in the call card */}
            {(["talk", "type"] as Mode[]).map((m) => (
              <button key={m} aria-pressed={mode === m} disabled={busy} title={busy ? "End the call to switch" : undefined} onClick={() => setMode(m)}
                className={cx("min-h-9 rounded-full px-4 py-1 text-sm font-semibold transition disabled:cursor-not-allowed",
                  mode === m ? "bg-accent text-on-accent" : "text-muted hover:bg-accent-soft disabled:hover:bg-transparent")}>
                {m === "talk" ? "Talk" : "Type"}
              </button>
            ))}
          </div>
        } actions={
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
              {status === "idle" && !events.length && <div className="pt-10 text-center text-sm text-muted">{outbound ? "Place the call: the agent opens the conversation, then you answer as the callee." : mode === "talk" ? "Start a call: the agent welcomes you first, then speak into your microphone (a headset works best)." : "Start a chat and type as the caller."}</div>}
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
            {status === "ended" && callId && <FeedbackPrompt key={callId} callId={callId} />}  {/* UI-34: only once the call has ended */}
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
          {agentUcs.length > 0 && (  // UI-24: one starting phrase per use case; callers' IDs live in the demo data
            <Card title={<button className="flex items-center gap-1" aria-expanded={scriptOpen} onClick={() => setScriptOpen(!scriptOpen)}>{scriptOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}Test script</button>}>
              {scriptOpen && (
                <ul className="space-y-3 text-sm">
                  {agentUcs.map((u) => {
                    const phrase: string | undefined = u.sample_utterances?.[0];
                    return (
                      <li key={u.id}>
                        <div className="text-xs font-medium text-muted">{u.title}</div>
                        {phrase && (canFill
                          ? <button className="mt-1 rounded-xl border border-line bg-panel px-3 py-1.5 text-left hover:border-accent" title="Fill the message box" onClick={() => setText(phrase)}>“{phrase}”</button>
                          : <div className="mt-1">“{phrase}”</div>)}
                      </li>
                    );
                  })}
                </ul>
              )}
            </Card>
          )}
          {technical && (  // UI-32: builder-facing details, off by default
            <>
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
            </>
          )}
        </div>
      </div>
    </div>
  );
}
