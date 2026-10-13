// Spec: /ui/visual-case.md
"use client";

import { Camera, ImageOff } from "lucide-react";
import { API_BASE } from "@/lib/api";
import { Badge, Card, cx } from "@/components/ui";

export type EvidenceEntry = {
  seq: number;
  media_id: string | null;
  source: "camera" | "sample";
  description: string;
  items: { label?: string; detail?: string }[];
  confidence: "confirmed" | "unclear" | "not_confirmed";
  safety_flag: string;
  asked_for: string;
  caller_words: string;
  at: string | null;
};

export type VisualCase = {
  kind: "facility_fault" | "claim";
  narrative: string;
  missing: string[];
  routing: "needs_docs" | "ready_for_review" | "siu_review" | "escalate";
  routing_reason: string;
  ticket_ref: string | null;
  sample_evidence?: boolean;
};

/**
 * "Not confirmed" is information, not an error. A danger tone here would teach the opposite of
 * what the whole feature is for, so it renders neutral (UI-41).
 */
const CONFIDENCE: Record<EvidenceEntry["confidence"], { label: string; tone: "ok" | "warn" | "neutral" }> = {
  confirmed: { label: "Confirmed", tone: "ok" },
  unclear: { label: "Unclear", tone: "warn" },
  not_confirmed: { label: "Not confirmed", tone: "neutral" },
};

const ROUTING_LABEL: Record<VisualCase["routing"], string> = {
  needs_docs: "Needs documents",
  ready_for_review: "Ready for review",
  siu_review: "Specialist review", // never the words "fraud" or "special investigations" (UI-42)
  escalate: "Escalate to a person",
};

const KIND_LABEL: Record<VisualCase["kind"], string> = {
  facility_fault: "Facility fault",
  claim: "Claim",
};

function Thumb({ entry }: { entry: EvidenceEntry }) {
  if (!entry.media_id) {
    return (
      <div className="flex h-20 w-28 shrink-0 flex-col items-center justify-center gap-1 rounded-lg bg-neutral-soft text-xs text-muted">
        <ImageOff size={16} />
        Image expired
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- authorised media endpoint, not a static asset
    <img
      src={`${API_BASE}/api/media/${entry.media_id}`}
      alt={`Frame ${entry.seq}: ${entry.description}`}
      className="h-20 w-28 shrink-0 rounded-lg object-cover"
      onError={(e) => {
        // Retention has removed the bytes; the finding stays readable (UI-44).
        const el = e.currentTarget;
        el.replaceWith(
          Object.assign(document.createElement("div"), {
            className:
              "flex h-20 w-28 shrink-0 items-center justify-center rounded-lg bg-neutral-soft text-xs text-muted",
            textContent: "Image expired",
          }),
        );
      }}
    />
  );
}

export function EvidenceStrip({ entries }: { entries: EvidenceEntry[] }) {
  if (!entries.length) return null;
  return (
    <Card title={<span className="flex items-center gap-2"><Camera size={14} />Evidence</span>}>
      <ul className="space-y-3">
        {entries.map((e) => {
          const c = CONFIDENCE[e.confidence] ?? CONFIDENCE.unclear;
          return (
            <li key={e.seq} className="flex gap-3 border-b border-line pb-3 last:border-0 last:pb-0">
              <Thumb entry={e} />
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={c.tone}>{c.label}</Badge>
                  {e.source === "sample" && <Badge tone="neutral">Sample</Badge>}
                  {e.safety_flag !== "none" && <Badge tone="bad">{e.safety_flag.replace("_", " ")}</Badge>}
                </div>
                <p className="text-sm">{e.description}</p>
                {e.caller_words && <p className="text-xs text-muted">Caller: “{e.caller_words}”</p>}
                {e.asked_for && <p className="text-xs text-muted">Agent asked for: {e.asked_for}</p>}
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

export function CaseCard({ visualCase }: { visualCase: VisualCase | null }) {
  if (!visualCase) return null;
  const c = visualCase;
  return (
    <Card title="Case" actions={<Badge tone="neutral">{KIND_LABEL[c.kind] ?? c.kind}</Badge>}>
      <div className="space-y-3 text-sm">
        {c.sample_evidence && (
          <div className="rounded-lg bg-neutral-soft px-3 py-2 text-xs text-muted">
            Built from synthetic demo images, not a real camera.
          </div>
        )}
        {c.narrative && <p>{c.narrative}</p>}
        <div>
          <div className="text-xs font-medium text-muted">Still needed</div>
          {c.missing.length ? (
            <ul className="mt-1 space-y-1">
              {c.missing.map((m) => (
                <li key={m} className="flex gap-2">
                  <span aria-hidden className="text-muted">☐</span>
                  <span>{m}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="mt-1 text-muted">Nothing outstanding</div>
          )}
        </div>
        <div>
          <div className="text-xs font-medium text-muted">Routing</div>
          <div className={cx("mt-1 font-medium")}>{ROUTING_LABEL[c.routing] ?? c.routing}</div>
          {c.routing_reason && <p className="text-xs text-muted">{c.routing_reason}</p>}
        </div>
        <div>
          <div className="text-xs font-medium text-muted">Ticket</div>
          <div className="mt-1 mono">{c.ticket_ref || <span className="font-sans text-muted">Recorded, not yet filed</span>}</div>
        </div>
      </div>
    </Card>
  );
}
