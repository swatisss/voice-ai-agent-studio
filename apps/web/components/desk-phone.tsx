// Spec: /ui/agent-desk.md (The browser as a phone, UI-91, UI-92)
"use client";

import { Mic, MicOff, Phone, PhoneOff } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { PacketCard } from "@/components/packet";
import { Badge, Button, useToast } from "@/components/ui";
import { api, type Escalation } from "@/lib/api";

type Phase = "offline" | "ready" | "ringing" | "on_call";
const PHASE_LABEL: Record<Phase, string> = { offline: "Offline", ready: "Ready", ringing: "Ringing", on_call: "On a call" };
const PHASE_TONE = { offline: "neutral", ready: "ok", ringing: "warn", on_call: "info" } as const;
const PRESENCE_EVERY_MS = 30_000;

// The slice of the Twilio Voice SDK Call and Device this component uses (the SDK is loaded on demand).
type VoiceCall = {
  accept(): void; ignore(): void; disconnect(): void; mute(on: boolean): void;
  on(event: string, handler: (...args: unknown[]) => void): void; customParameters?: Map<string, string>;
};
type VoiceDevice = {
  register(): Promise<void>; unregister(): Promise<void>; destroy(): void; updateToken(token: string): void;
  on(event: string, handler: (...args: unknown[]) => void): void;
};

/** "Take calls in this browser": switch, presence, incoming-handover banner and call bar. Hidden without the Voice SDK key. */
export function DeskPhone({ items, onSelect, onChanged }: { items: Escalation[]; onSelect: (id: string) => void; onChanged: () => void }) {
  const toast = useToast();
  const [available, setAvailable] = useState(false);
  const [on, setOn] = useState(false);
  const [phase, setPhase] = useState<Phase>("offline");
  const [incoming, setIncoming] = useState<{ call: VoiceCall; callId: string | null } | null>(null);
  const [recorded, setRecorded] = useState(false);
  const [muted, setMuted] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const device = useRef<VoiceDevice | null>(null);
  const active = useRef<VoiceCall | null>(null);
  const beat = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {  // UI-91: the control is not shown with providers.twilio_voice_sdk false
    api("/healthz").then((h: { providers?: { twilio_voice_sdk?: boolean } }) => setAvailable(Boolean(h?.providers?.twilio_voice_sdk))).catch(() => setAvailable(false));
  }, []);

  useEffect(() => {
    if (phase !== "on_call") return;
    setSeconds(0);
    const t = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [phase]);

  const presence = useCallback((ready: boolean) => api("/api/desk/phone-presence", { method: "PUT", json: { ready } }).catch(() => undefined), []);

  const stop = useCallback(async () => {
    if (beat.current) clearInterval(beat.current);
    beat.current = null;
    try { await presence(false); } catch { /* the server ends presence after 90 seconds anyway */ }
    try { device.current?.destroy(); } catch { /* already gone */ }
    device.current = null; active.current = null;
    setOn(false); setPhase("offline"); setIncoming(null);
  }, [presence]);

  useEffect(() => () => { void stop(); }, [stop]);  // closing the page sets Offline

  async function start() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });  // the microphone is requested first
      stream.getTracks().forEach((t) => t.stop());
      const { token } = await api("/api/desk/phone-token", { method: "POST" });
      const { Device } = await import("@twilio/voice-sdk");
      const d = new Device(token, { codecPreferences: ["opus", "pcmu"] as never }) as unknown as VoiceDevice;
      d.on("error", () => { toast("The phone connection failed. You are Offline.", "bad"); void stop(); });
      d.on("tokenWillExpire", () => { api("/api/desk/phone-token", { method: "POST" }).then((r) => d.updateToken(r.token)).catch(() => void stop()); });
      d.on("incoming", (c) => {
        const call = c as VoiceCall;
        const callId = call.customParameters?.get("call_id") ?? null;
        call.on("cancel", () => { setIncoming(null); setPhase("ready"); });  // another leg answered or nobody did
        call.on("disconnect", () => { active.current = null; setPhase("ready"); onChanged(); });
        setIncoming({ call, callId }); setPhase("ringing");
      });
      await d.register();
      device.current = d;
      await presence(true);
      beat.current = setInterval(() => void presence(true), PRESENCE_EVERY_MS);
      setOn(true); setPhase("ready");
    } catch (e) {
      toast(e instanceof Error && e.name === "NotAllowedError" ? "Allow the microphone to take calls here." : "Could not start the browser phone.", "bad");
      await stop();
    }
  }

  const ringing: Escalation | undefined = incoming
    ? (incoming.callId ? items.find((e) => e.call_id === incoming.callId) : undefined) ?? items.filter((e) => e.status === "waiting")[0]
    : undefined;

  async function answer() {
    if (!incoming) return;
    incoming.call.accept();
    active.current = incoming.call;
    setPhase("on_call"); setMuted(false);
    if (ringing) {
      onSelect(ringing.id);
      try { await api(`/api/escalations/${ringing.id}/accept`, { method: "POST", json: { assignee: "Specialist" } }); } catch { /* already accepted by the handover */ }
      try { const c = await api(`/api/calls/${ringing.call_id}`); setRecorded(Boolean(c?.handover?.record)); } catch { setRecorded(false); }
      onChanged();
    }
    setIncoming(null);
  }

  function decline() {  // leaves the call ringing for others
    incoming?.call.ignore();
    setIncoming(null); setPhase("ready");
  }

  if (!available) return null;
  const mmss = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  return (
    <div className="space-y-2" data-testid="desk-phone">
      <div className="flex items-center gap-2">
        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <input type="checkbox" role="switch" checked={on} onChange={() => (on ? void stop() : void start())} aria-label="Take calls in this browser" />
          Take calls in this browser
        </label>
        <Badge tone={PHASE_TONE[phase]}>{PHASE_LABEL[phase]}</Badge>
      </div>
      {phase === "ringing" && incoming && (
        <div className="space-y-2 rounded-xl border border-warn bg-panel p-3" role="alert" data-testid="incoming-handover">
          <div className="flex items-center gap-2 text-sm font-medium"><Phone size={16} /> Incoming handover</div>
          {ringing ? <PacketCard esc={ringing} /> : <div className="text-sm text-muted">A caller needs a person. The details are on the escalation.</div>}
          <div className="flex gap-2">
            <Button variant="primary" onClick={answer}>Answer</Button>
            <Button variant="ghost" onClick={decline}>Decline</Button>
          </div>
        </div>
      )}
      {phase === "on_call" && (
        <div className="flex items-center gap-3 rounded-xl border border-line bg-panel p-3" data-testid="call-bar">
          <span className="mono text-sm" aria-label="Call timer">{mmss}</span>
          {recorded && <Badge tone="warn">Recorded</Badge>}
          <Button variant="ghost" onClick={() => { active.current?.mute(!muted); setMuted(!muted); }} aria-pressed={muted}>
            {muted ? <MicOff size={16} /> : <Mic size={16} />} {muted ? "Unmute" : "Mute"}
          </Button>
          <Button variant="danger" onClick={() => active.current?.disconnect()}><PhoneOff size={16} /> Hang up</Button>
        </div>
      )}
    </div>
  );
}
