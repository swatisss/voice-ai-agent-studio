// Spec: /ui/design-system.md (Copy rules)
export const money = (n: number | null | undefined, digits = 0) =>
  n == null ? "—" : `$${n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
export const pct = (r: number | null | undefined) => (r == null ? "—" : `${Math.round(r * 100)}%`);
export const secs = (ms: number | null | undefined) => (ms == null ? "—" : `${(ms / 1000).toFixed(1)} s`);
export const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—";
export const ago = (iso: string) => {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h`;
};
export const maskRef = (ref: string | null | undefined) => (ref ? ref.replace(/^(EVG-)(\d+)(\d{3})$/, (_, p, mid, end) => `${p}${"•".repeat(mid.length)}${end}`) : "—");

export const ROOT_CAUSE: Record<string, string> = {
  none: "None", missing_knowledge: "Missing knowledge", missing_skill: "Missing skill", policy_required: "Policy required",
  safety: "Safety", caller_requested: "Caller requested", tool_error: "Tool error", asr_error: "Speech error",
  agent_error: "Agent error", other: "Other",
};
export const REASON: Record<string, string> = {
  caller_requested: "Caller requested", policy_required: "Policy required", safety: "Safety", knowledge_gap: "Knowledge gap",
  capability_gap: "Capability gap", tool_failure: "Tool failure", frustration: "Frustration", other: "Other",
};
export const DISPOSITIONS = ["resolved_by_human", "appeal_filed", "callback_scheduled", "transferred_department", "no_action_needed", "other"];
export const label = (s: string | null | undefined) => (s ? s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()) : "—");
export const outcomeTone = (o: string | null | undefined): Tone => (o === "resolved" ? "ok" : o === "escalated" ? "warn" : "neutral");
export type Tone = "ok" | "warn" | "bad" | "info" | "neutral" | "accent";
export const MODE_LABEL: Record<string, string> = { inbound: "Inbound", outbound: "Outbound", internal: "Internal" };
export const MODE_TONE: Record<string, Tone> = { inbound: "accent", outbound: "info", internal: "neutral" };
