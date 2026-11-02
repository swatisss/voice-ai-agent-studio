// Spec: /ui/insights.md (Cluster list labels)
"use client";

import { Badge } from "./ui";

/** The fix verification of /architecture/learning-actions.md: did the approved fix hold? (UI-68) */
export function FixLine({ c }: { c: any }) {
  const f = c.fix;
  if (!f) return null;
  if (f.held === false) return <div className="mt-2 text-sm text-bad">Fix in v{f.version} did not hold: {f.before_per_week}/week before, {f.after_per_week}/week since</div>;
  if (f.held) return <div className="mt-2 text-sm text-ok">Fix in v{f.version} held: {f.before_per_week}/week → {f.after_per_week}/week</div>;
  return <div className="mt-2 text-sm text-muted">Fix in v{f.version}: watching ({f.before_per_week}/week before, {f.after_per_week}/week since)</div>;
}

export function ClusterLabel({ c }: { c: any }) {
  if (c.fix?.held === false && c.status !== "fixed") return <Badge tone="bad">Fix did not hold</Badge>;
  const map: Record<string, [string, "accent" | "ok" | "neutral" | "warn" | "bad"]> = {
    ready_for_fix: ["Ready for fix", "accent"], fix_proposed: ["Fix proposed", "ok"], fixed: [c.fix?.version ? `Fixed in v${c.fix.version}` : "Fixed", "ok"],
    correct_escalation: ["Correct escalation — no fix", "neutral"], investigate: ["Investigate", "warn"], ignored: ["Ignored", "neutral"],
    snoozed: ["Snoozed after a rejection", "neutral"],
  };
  if (c.label === "watching") return <Badge>{`Watching (${c.signal_count ?? c.escalations_28d ?? c.escalation_count} of ${c.min_cluster_size})`}</Badge>;
  const [text, tone] = map[c.label] ?? [c.label, "neutral"];
  return <Badge tone={tone}>{text}</Badge>;
}
