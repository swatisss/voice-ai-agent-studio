// Spec: /ui/agent-desk.md (WhatsApp conversations, UI-94, UI-95)
"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui";

export type ChannelState = {
  channel: "whatsapp"; window_open: boolean; window_expires_at: string | null; opted_out: boolean; mode: "sandbox" | "production"; address_last4?: string;
};

const DELIVERY: Record<string, { label: string; tone: "neutral" | "ok" | "warn" | "bad" | "info" }> = {
  sending: { label: "Sending", tone: "neutral" }, sent: { label: "Sent", tone: "neutral" }, delivered: { label: "Delivered", tone: "info" },
  read: { label: "Read", tone: "ok" }, failed: { label: "Failed", tone: "bad" }, undelivered: { label: "Not delivered", tone: "bad" },
  queued_template: { label: "Queued", tone: "warn" },
};

/** Time left in the 24-hour reply window as "5 h 12 min"; null once it has closed. */
export function windowLeft(expires: string | null, now = Date.now()): string | null {
  if (!expires) return null;
  const ms = new Date(expires).getTime() - now;
  if (ms <= 0) return null;
  const mins = Math.floor(ms / 60_000);
  return mins >= 60 ? `${Math.floor(mins / 60)} h ${mins % 60} min` : `${Math.max(mins, 1)} min`;
}

/** Whether the specialist can type: an opted-out customer and a closed sandbox window disable the composer (UI-94, UI-95). */
export function composerNote(cs: ChannelState | null | undefined): string | null {
  if (!cs) return null;
  if (cs.opted_out) return "The customer has opted out of messages (they sent STOP). You cannot reply until they write again.";
  if (!cs.window_open && cs.mode === "sandbox") return "Sandbox: replies only inside the 24-hour window";
  return null;
}

export function useNow(everyMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), everyMs); return () => clearInterval(t); }, [everyMs]);
  return now;
}

/** Badge, customer and reply-window countdown above the conversation (amber under one hour). */
export function WhatsappStatus({ state }: { state: ChannelState }) {
  const now = useNow();
  const left = windowLeft(state.window_expires_at, now);
  const under = left !== null && new Date(state.window_expires_at!).getTime() - now < 3_600_000;
  return (
    <div className="mb-3 space-y-2" data-testid="whatsapp-status">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge tone="ok">WhatsApp</Badge>
        <span className="text-muted">Customer {state.address_last4 ? `wa-…${state.address_last4}` : "wa-…"}</span>
        {state.mode === "sandbox" && <Badge tone="neutral">Sandbox</Badge>}
        <span className="ml-auto" data-testid="window-countdown">
          {left ? <Badge tone={under ? "warn" : "info"}>Reply window: {left} left</Badge> : <Badge tone="bad">Reply window closed</Badge>}
        </span>
      </div>
      {!state.window_open && state.mode === "production" && !state.opted_out && (
        <div className="rounded-lg bg-neutral-soft p-2 text-xs" data-testid="template-notice">
          The 24-hour window has closed. Your reply is queued and the customer gets an approved follow-up message first; your text is delivered when they answer.
        </div>
      )}
      {composerNote(state) && <div className="rounded-lg bg-neutral-soft p-2 text-xs" data-testid="composer-note">{composerNote(state)}</div>}
    </div>
  );
}

/** The delivery state under one of the specialist's messages. */
export function DeliveryMark({ delivery }: { delivery?: string }) {
  const d = delivery ? DELIVERY[delivery] : undefined;
  return d ? <div className="mt-1 text-[11px] opacity-90" data-testid="delivery">{d.label}</div> : null;
}
