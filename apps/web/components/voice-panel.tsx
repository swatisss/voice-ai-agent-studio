// Spec: /ui/agent-desk.md (Voice panel, LKH-25..LKH-28), /ui/agent-console.md, /architecture/hosted-media-room.md
"use client";

import { Mic, MicOff, Phone, PhoneOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Badge, Button, Card, useToast } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { RoomClient } from "@/lib/room";

/** Whole seconds since an ISO time, ticking once a second. */
export function useElapsed(since: string | null | undefined): number {
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((x) => x + 1), 1000); return () => clearInterval(t); }, []);
  return since ? Math.max(0, Math.floor((Date.now() - new Date(since).getTime()) / 1000)) : 0;
}

/** LKH-25: the console card's strip for a voice escalation; nothing for an escalation without a media room. */
export function VoiceStrip({ esc }: { esc: { voice_state?: string | null; created_at: string } }) {
  const secs = useElapsed(esc.created_at);
  if (esc.voice_state !== "waiting") return null;
  return <div className="mt-1 text-xs font-medium text-warn">Live voice - customer waiting <span className="mono">{secs} s</span></div>;
}

type Phase = "idle" | "joining" | "connected" | "left";

/**
 * LKH-26..LKH-28: take the call, mute, hang up (leave the room; the customer is on hold), then Resolve as usual.
 * The microphone permission is asked before the token is requested; the token is used once and never shown.
 */
export function VoicePanel({ esc, onChanged }: { esc: any; onChanged: () => void }) {
  const toast = useToast();
  const [phase, setPhase] = useState<Phase>("idle");
  const [muted, setMuted] = useState(false);
  const client = useRef<RoomClient | null>(null);
  useEffect(() => () => client.current?.hangup(), []);
  useEffect(() => { if (esc.voice_state === "ended") { client.current?.hangup(); client.current = null; } }, [esc.voice_state]);

  if (!esc.voice_state) return null;
  const ended = esc.voice_state === "ended" || esc.status === "resolved";
  const canTake = !ended && esc.voice_state === "waiting" && (esc.status === "waiting" || phase === "left" || phase === "idle");

  async function take() {
    setPhase("joining");
    try {
      const probe = await navigator.mediaDevices.getUserMedia({ audio: true });  // ask for the microphone first (LKH-26)
      probe.getTracks().forEach((t) => t.stop());
    } catch {
      setPhase("idle");
      toast("Microphone access was denied. Allow it in the browser and try again.", "bad");
      return;
    }
    try {
      const r = await api(`/api/escalations/${esc.id}/voice/join`, { method: "POST", json: {} });
      const rc = new RoomClient({ onConnected: () => setPhase("connected"), onClose: () => setPhase((p) => (p === "connected" ? "left" : p)) });
      client.current = rc;
      await rc.start(r.url, r.token);
      setMuted(false);
      onChanged();
    } catch (e) {
      client.current?.hangup(); client.current = null;
      setPhase("idle");
      toast(e instanceof ApiError ? e.detail : "Could not join the call", "bad");
    }
  }

  async function toggleMute() {
    const next = !muted;
    await client.current?.setMuted(next);
    setMuted(next);
  }

  function leave() {  // LKH-27: leaves the room; the customer hears hold
    client.current?.hangup(); client.current = null;
    setPhase("left");
  }

  return (
    <Card title="Live voice" actions={<Badge tone={ended ? "neutral" : phase === "connected" ? "ok" : "warn"}>{ended ? "Call ended" : phase === "connected" ? (muted ? "Muted" : "Connected") : phase === "joining" ? "Joining" : phase === "left" ? "Customer on hold" : "Customer waiting"}</Badge>}>
      {ended && <p className="text-sm text-muted">Call ended.</p>}
      {!ended && canTake && phase !== "joining" && (
        <div className="space-y-2">
          <p className="text-sm text-muted">The AI introduces you and leaves. Use a headset to avoid echo.</p>
          <Button variant="primary" onClick={take}><Phone size={14} />Take the call</Button>
        </div>
      )}
      {!ended && phase === "joining" && <p className="text-sm text-muted">Joining…</p>}
      {!ended && phase === "connected" && (
        <div className="flex gap-2">
          <Button onClick={toggleMute} aria-pressed={muted}>{muted ? <MicOff size={14} /> : <Mic size={14} />}{muted ? "Unmute" : "Mute"}</Button>
          <Button variant="danger" onClick={leave}><PhoneOff size={14} />Hang up</Button>
        </div>
      )}
    </Card>
  );
}
