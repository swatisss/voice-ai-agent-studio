// Spec: /ui/test-call.md (Full flow), /architecture/supervisor-routing.md (Playground, Routing record), /architecture/agent-transfer.md
"use client";

import { Mic, PhoneOff, Send } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { FeedbackPrompt } from "@/components/feedback";
import { Badge, Button, Card, cx, Input, Select, useToast } from "@/components/ui";
import { api, ApiError, useApi, useEvents } from "@/lib/api";
import { VoiceClient } from "@/lib/voice";

type Mode = "talk" | "type";
type Line = { segment: number | null; speaker: "caller" | "agent" | "front_desk"; text: string; agent_name?: string | null };
type Decision = {
  at: string; trigger: string; method: string; agent_id: string | null; confidence: number | null; reason: string;
  candidates: { agent_id: string; score: number }[]; stage_b: { target: string; model: string; choice: string; confidence: number; ms: number } | null;
  fallbacks: { target: string; error: string }[]; clarification: string | null; stage_a_ms?: number; excluded?: string[]; mode?: string;
};
type View = {
  id: string; status: string; outcome: string | null; agent: { id: string; name: string } | null; routing: Decision[];
  segments: { call_id: string; agent_id: string; agent_name: string; segment: number; routed_by: string; outcome: string | null }[];
  transcript: Line[]; escalation: { id: string; status: string } | null;
};

const ROUTING_MODE: Record<string, string> = { embedding: "Embedding", decision_model: "Decision model" };
const FALLBACK: Record<string, string> = {
  not_configured: "not configured", phi_mode: "blocked by PHI mode", timeout: "timed out", invalid_answer: "gave an invalid answer", unsure: "was unsure",
};

const METHOD: Record<string, string> = {
  explicit: "Chosen by the caller's system", single: "Only agent for this audience", embedding: "Clear match (Stage A)", decision: "Decision model",
  llm: "LLM router", clarify: "Asked a clarifying question", clarified: "After clarifying", default: "Default agent", transfer: "Transfer", none: "No agent",
};

export function RoutingTrace({ decisions, names }: { decisions: Decision[]; names: Record<string, string> }) {
  if (!decisions.length) return <p className="text-sm text-muted">No routing yet. Say or type what you need.</p>;
  return (
    <ol className="space-y-4 text-sm">
      {[...decisions].reverse().map((d, i) => (
        <li key={`${d.at}-${i}`} className="space-y-1 border-b border-[var(--border)] pb-3 last:border-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={d.trigger === "transfer" ? "warn" : "info"}>{d.trigger === "transfer" ? "Transfer" : d.trigger === "start" ? "Start" : d.trigger}</Badge>
            <span className="font-medium">{d.agent_id ? names[d.agent_id] ?? d.agent_id : d.clarification ? "Clarifying" : "No agent"}</span>
            {d.confidence != null && <span className="text-muted">{d.confidence.toFixed(2)}</span>}
            {d.mode && <Badge tone="neutral">{ROUTING_MODE[d.mode] ?? d.mode}</Badge>}
          </div>
          <div className="text-muted">{METHOD[d.method] ?? d.method}{d.reason ? ` — ${d.reason}` : ""}</div>
          {d.candidates?.length > 0 && (
            <ul className="space-y-0.5">
              {d.candidates.map((c) => (
                <li key={c.agent_id} className="flex items-center gap-2">
                  <span className="w-40 truncate">{names[c.agent_id] ?? c.agent_id}</span>
                  <span className="h-2 flex-1 rounded bg-neutral-soft"><span className="block h-2 rounded bg-accent" style={{ width: `${Math.max(0, Math.min(1, c.score)) * 100}%` }} /></span>
                  <span className="w-10 text-right tabular-nums text-muted">{c.score.toFixed(2)}</span>
                </li>
              ))}
            </ul>
          )}
          {d.stage_b && <div className="text-muted">Decision model chose {d.stage_b.choice === "none" ? "none" : names[d.stage_b.choice] ?? d.stage_b.choice} at {d.stage_b.confidence.toFixed(2)} in {d.stage_b.ms} ms</div>}
          {d.fallbacks?.length > 0 && <div className="text-warn">{d.fallbacks.map((f) => `${f.target === "decision_model" ? "Decision model" : f.target} ${FALLBACK[f.error] ?? f.error.replace(/_/g, " ")}`).join(" · ")} → embedding</div>}
          {d.clarification && <div>Asked: &ldquo;{d.clarification}&rdquo;</div>}
        </li>
      ))}
    </ol>
  );
}

const CALL_FROM: { id: string; label: string; number?: string }[] = [
  { id: "none", label: "No number" },
  { id: "sarah", label: "Sarah Mitchell — registered number", number: "+447700900141" },
  { id: "david", label: "David Okoro — registered number", number: "+447700900142" },
  { id: "unknown", label: "An unknown number", number: "+447700900199" },
];

export function FullFlow({ tenant, technical }: { tenant: string; technical: boolean }) {
  const toast = useToast();
  const { data: agents } = useApi<{ items: { id: string; name: string; mode: string; published_version: unknown }[] }>("/api/agents", [tenant]);
  const { data: useCases } = useApi<{ items: any[] }>("/api/use-cases", [tenant]);
  const [scope, setScope] = useState<"member" | "staff">("member");
  const [mode, setMode] = useState<Mode>("type");
  const [callFrom, setCallFrom] = useState("none");
  const [convId, setConvId] = useState<string | null>(null);
  const [view, setView] = useState<View | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [status, setStatus] = useState<"idle" | "connecting" | "active" | "ended">("idle");
  const [text, setText] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [level, setLevel] = useState(0);
  const [speaking, setSpeaking] = useState(false);
  const voice = useRef<VoiceClient | null>(null);
  const names = Object.fromEntries((agents?.items ?? []).map((a) => [a.id, a.name]));
  const audienceAgents = (agents?.items ?? []).filter((a) => a.published_version && a.mode === (scope === "member" ? "inbound" : "internal"));
  const ucs = (useCases?.items ?? []).filter((u) => audienceAgents.some((a) => a.id === u.agent_id));

  const refresh = useCallback(async (id: string) => {
    const v = await api<View>(`/api/conversations/${id}`);
    setView(v);
    if (v.transcript.length) setLines(v.transcript);
    if (v.status === "ended") setStatus("ended");
  }, []);

  useEvents(convId ? [`conversation:${convId}`] : [], () => { if (convId) refresh(convId); }, tenant);
  useEffect(() => {  // voice transcripts arrive as the call goes: refresh while it runs
    if (!convId || mode !== "talk" || status !== "active") return;
    const t = setInterval(() => refresh(convId), 1500);
    return () => clearInterval(t);
  }, [convId, mode, status, refresh]);
  useEffect(() => () => voice.current?.hangup(), []);

  function reset() {
    voice.current?.hangup();
    voice.current = null;
    setConvId(null); setView(null); setLines([]); setStatus("idle"); setLevel(0); setSpeaking(false);
  }

  async function start() {
    reset();
    setStatus("connecting");
    const number = scope === "member" ? CALL_FROM.find((o) => o.id === callFrom)?.number : undefined;
    try {
      const r = await api("/api/conversations", { method: "POST", json: { channel: mode === "talk" ? "voice" : "text", scope, caller: number ? { number } : undefined } });
      setConvId(r.conversation_id);
      if (mode === "type") {
        setLines(r.messages.map((m: any) => ({ segment: null, speaker: m.speaker, text: m.text })));
        setStatus("active");
        await refresh(r.conversation_id);
        return;
      }
      const client = new VoiceClient({
        onReady: () => setStatus("active"), onLevel: setLevel, onSpeaking: setSpeaking,
        onEnd: () => { setStatus("ended"); refresh(r.conversation_id); },
        onClose: (code) => {
          if (code === 4500) toast("Voice is unavailable (speech provider key missing) — use Type mode", "bad");
          setStatus("ended");
          refresh(r.conversation_id);
        },
      });
      voice.current = client;
      await client.startConnect(r.connect.url, r.connect.token);
    } catch (e) {
      setStatus("idle");
      toast(e instanceof ApiError ? e.detail : `Could not start: ${(e as Error).message}`, "bad");
    }
  }

  async function send() {
    if (!convId || !text.trim()) return;
    const msg = text.trim();
    setText("");
    setLines((l) => [...l, { segment: null, speaker: "caller", text: msg }]);
    setWaiting(true);
    try {
      const r = await api(`/api/conversations/${convId}/messages`, { method: "POST", json: { text: msg } });
      if (r.ended) setStatus("ended");
      await refresh(convId);
    } catch (e) {
      toast((e as ApiError).detail, "bad");
    } finally {
      setWaiting(false);
    }
  }

  async function hangup() {
    if (!convId) return;
    if (voice.current) { voice.current.hangup(); voice.current = null; }
    else await api(`/api/conversations/${convId}/end`, { method: "POST" }).catch(() => undefined);
    setStatus("ended");
    setTimeout(() => refresh(convId), 400);
  }

  const busy = status === "active" || status === "connecting";
  const segOf = (n: number | null) => view?.segments.find((s) => s.segment === n);
  const lastCall = view?.segments.at(-1)?.call_id;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm text-muted" htmlFor="audience">Audience</label>
        <Select id="audience" className="w-40" value={scope} disabled={busy} onChange={(e) => setScope(e.target.value as "member" | "staff")}>
          <option value="member">Members</option><option value="staff">Staff</option>
        </Select>
      </div>
      {ucs.length > 0 && <p className="text-sm text-muted"><span className="font-medium text-fg">Handles:</span> {ucs.map((u) => u.title).join(" · ")}</p>}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" title={
          <div className="flex gap-1" role="group" aria-label="Call type">
            {(["talk", "type"] as Mode[]).map((m) => (
              <button key={m} aria-pressed={mode === m} disabled={busy} onClick={() => setMode(m)}
                className={cx("min-h-9 rounded-full px-4 py-1 text-sm font-semibold transition disabled:cursor-not-allowed",
                  mode === m ? "bg-accent text-on-accent" : "text-muted hover:bg-accent-soft disabled:hover:bg-transparent")}>
                {m === "talk" ? "Talk" : "Type"}
              </button>
            ))}
          </div>
        } actions={busy
          ? <Button variant="danger" onClick={hangup}><PhoneOff size={14} />{mode === "talk" ? "Hang up" : "End chat"}</Button>
          : <Button variant="primary" onClick={start} disabled={!audienceAgents.length}>{mode === "talk" ? "Start call" : "Start chat"}</Button>}>
          {scope === "member" && (
            <div className="mb-3 max-w-md space-y-1">
              <label className="text-xs font-medium text-muted" htmlFor="ff-call-from">Call from</label>
              <Select id="ff-call-from" value={callFrom} disabled={busy} onChange={(e) => setCallFrom(e.target.value)}>
                {CALL_FROM.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
              </Select>
            </div>
          )}
          <div className="flex h-[52vh] flex-col">
            <div className="flex-1 space-y-2 overflow-y-auto pr-1">
              {status === "idle" && !lines.length && <div className="pt-10 text-center text-sm text-muted">The front desk answers first. Say or type what you need: the supervisor picks the agent.</div>}
              {lines.map((l, i) => {
                const prev = lines[i - 1];
                const seg = segOf(l.segment);
                const notice = l.segment && prev?.segment !== l.segment && seg
                  ? seg.routed_by === "transfer" ? `Transferred to ${seg.agent_name}` : `Routed to ${seg.agent_name}${view?.routing.find((d) => d.agent_id === seg.agent_id)?.confidence != null ? ` · ${view?.routing.find((d) => d.agent_id === seg.agent_id)!.confidence!.toFixed(2)}` : ""}`
                  : null;
                return (
                  <div key={i}>
                    {notice && l.speaker !== "front_desk" && <div className="my-2 text-center text-xs text-muted">{notice}</div>}
                    <div className={cx("flex", l.speaker === "caller" ? "justify-end" : "justify-start")}>
                      <div className={cx("max-w-[80%] rounded-2xl px-3 py-2 text-sm", l.speaker === "caller" ? "bg-accent text-on-accent" : "bg-neutral-soft")}>
                        {l.speaker !== "caller" && <div className="mb-0.5 text-xs font-medium text-muted">{l.speaker === "front_desk" ? "Front desk" : l.agent_name ?? (seg?.agent_name ?? "Agent")}</div>}
                        {l.text}
                      </div>
                    </div>
                  </div>
                );
              })}
              {waiting && <div className="text-sm text-muted">Working…</div>}
            </div>
            {status === "ended" && (
              <div className={cx("mt-3 rounded-lg px-3 py-2 text-sm", view?.escalation ? "bg-warn-soft text-warn" : "bg-neutral-soft")}>
                {view?.escalation ? "Escalated — waiting for a specialist" : "Conversation ended"}
                <Button variant="ghost" className="ml-3" onClick={start}>Start new conversation</Button>
              </div>
            )}
            {status === "ended" && lastCall && <FeedbackPrompt key={lastCall} callId={lastCall} />}
            {mode === "type" && status === "active" && (
              <div className="mt-3 flex gap-2">
                <Input value={text} disabled={waiting} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} placeholder="Type as the caller…" />
                <Button variant="primary" onClick={send} disabled={waiting || !text.trim()}><Send size={14} /></Button>
              </div>
            )}
            {mode === "talk" && busy && (
              <div className="mt-3 flex items-center justify-center gap-6">
                <div className={cx("flex h-16 w-16 items-center justify-center rounded-full bg-accent text-on-accent", speaking && "speaking")}
                  style={{ transform: `scale(${1 + Math.min(level * 4, 0.35)})` }}><Mic size={26} /></div>
                <div className="text-sm text-muted">{status === "connecting" ? "Connecting…" : speaking ? "Speaking" : "Listening"}</div>
              </div>
            )}
          </div>
        </Card>
        <div className="space-y-4">
          <Card title="Routing"><RoutingTrace decisions={view?.routing ?? []} names={names} /></Card>
          {ucs.length > 0 && (
            <Card title="Test script">
              <ul className="space-y-3 text-sm">
                {ucs.map((u) => (
                  <li key={u.id}>
                    <div className="text-xs font-medium text-muted">{names[u.agent_id]} · {u.title}</div>
                    {u.sample_utterances?.[0] && (mode === "type" && status === "active"
                      ? <button className="mt-1 rounded-xl border border-line bg-panel px-3 py-1.5 text-left hover:border-accent" onClick={() => setText(u.sample_utterances[0])}>“{u.sample_utterances[0]}”</button>
                      : <div className="mt-1">“{u.sample_utterances[0]}”</div>)}
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {technical && (
            <Card title="Conversation">
              {convId ? (
                <div className="space-y-1 text-sm">
                  <div><span className="text-muted">Conversation</span> <span className="mono">{convId.slice(0, 8)}</span></div>
                  {view?.segments.map((s) => (
                    <div key={s.call_id}>Segment {s.segment}: <Link className="text-accent" href={`/calls/detail/?id=${s.call_id}`}>{s.agent_name}</Link> <span className="text-muted">({s.routed_by})</span></div>
                  ))}
                </div>
              ) : <div className="text-sm text-muted">No conversation yet.</div>}
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
