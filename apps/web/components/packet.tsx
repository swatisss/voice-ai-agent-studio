// Spec: /ui/agent-console.md (Packet card), /architecture/escalation.md (Groundwork packet), /ui/visual-case.md
"use client";

import { ArrowRight, CheckSquare, TrendingDown, TrendingUp, Minus } from "lucide-react";
import type { Escalation } from "@/lib/api";
import { API_BASE } from "@/lib/api";
import { label, REASON, type Tone } from "@/lib/format";
import { Badge } from "./ui";

type PacketEvidence = { media_id: string | null; source: string; description: string; confidence: string; asked_for: string };

const CONFIDENCE_TONE: Record<string, Tone> = { confirmed: "ok", unclear: "warn", not_confirmed: "neutral" };

/**
 * The frames the agent looked at, above the summary: the specialist sees what it saw before
 * reading what it concluded. Appended to the packet deterministically, so it is here on a
 * fallback packet too (ES-09).
 */
function VisualEvidence({ entries }: { entries: PacketEvidence[] }) {
  if (!entries?.length) return null;
  return (
    <div className="space-y-2 rounded-lg bg-neutral-soft p-3">
      <div className="text-xs font-medium text-muted">What the agent saw</div>
      <ul className="space-y-2">
        {entries.map((e, i) => (
          <li key={i} className="flex gap-3">
            {e.media_id ? (
              // eslint-disable-next-line @next/next/no-img-element -- authorised media endpoint
              <img src={`${API_BASE}/api/media/${e.media_id}`} alt={e.description}
                className="h-14 w-20 shrink-0 rounded object-cover" />
            ) : (
              <div className="flex h-14 w-20 shrink-0 items-center justify-center rounded bg-panel text-[10px] text-muted">Image expired</div>
            )}
            <div className="min-w-0 space-y-1">
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge tone={CONFIDENCE_TONE[e.confidence] ?? "neutral"}>{label(e.confidence)}</Badge>
                {e.source === "sample" && <Badge tone="neutral">Sample</Badge>}
              </div>
              <p className="text-sm">{e.description}</p>
              {e.asked_for && <p className="text-xs text-muted">Agent asked for: {e.asked_for}</p>}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

const sentimentTone = (s: string): Tone => (s === "positive" ? "ok" : s === "neutral" ? "neutral" : s === "distressed" || s === "angry" ? "bad" : "warn");

export function PacketCard({ esc }: { esc: Escalation }) {
  if (esc.packet_status === "pending" || !esc.packet) {
    return (
      <div className="space-y-2 rounded-xl border border-line bg-panel p-4">
        <div className="text-sm text-muted">Preparing handoff notes…</div>
        <div className="h-4 w-3/4 animate-pulse rounded bg-neutral-soft" />
        <div className="h-4 w-1/2 animate-pulse rounded bg-neutral-soft" />
      </div>
    );
  }
  const p = esc.packet;
  const Trend = p.sentiment.trend === "declining" ? TrendingDown : p.sentiment.trend === "improving" ? TrendingUp : Minus;
  return (
    <div className="space-y-3 rounded-xl border border-line bg-panel p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={esc.reason_category === "safety" ? "bad" : "warn"}>{REASON[esc.reason_category] ?? label(esc.reason_category)}</Badge>
        <Badge tone="info">{label(p.intent)}</Badge>
        <Badge tone={p.caller_verified ? "ok" : "neutral"}>{p.caller_verified ? "Identity verified" : "Not verified"}</Badge>
        {esc.packet_status === "fallback" && <span className="text-xs text-muted">Basic notes (AI summary unavailable)</span>}
      </div>
      <VisualEvidence entries={(p as unknown as { visual_evidence?: PacketEvidence[] }).visual_evidence ?? []} />
      <p className="text-base leading-relaxed">{p.summary}</p>
      {Object.keys(p.entities ?? {}).length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(p.entities).map(([k, v]) => <Badge key={k} tone="neutral"><span className="text-muted">{label(k)}:</span> <span className="mono">{String(v)}</span></Badge>)}
        </div>
      )}
      {p.already_tried?.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-medium text-muted">Already tried</div>
          <ul className="space-y-1">
            {p.already_tried.map((t, i) => <li key={i} className="flex gap-2 text-sm"><CheckSquare size={15} className="mt-0.5 shrink-0 text-ok" />{t}</li>)}
          </ul>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-xs text-muted">Sentiment</span>
        <Badge tone={sentimentTone(p.sentiment.start)}>{p.sentiment.start}</Badge>
        <ArrowRight size={14} className="text-muted" />
        <Badge tone={sentimentTone(p.sentiment.end)}>{p.sentiment.end}</Badge>
        <Trend size={15} className="text-muted" />
      </div>
      <div className="rounded-lg bg-accent-soft px-3 py-2 text-sm"><span className="font-medium text-accent">Suggested next step: </span>{p.suggested_next_action}</div>
      {p.escalation_reason?.detail && <div className="text-xs text-muted">Reason: {p.escalation_reason.detail}</div>}
    </div>
  );
}
