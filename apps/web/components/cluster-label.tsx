// Spec: /ui/insights.md (Cluster list labels)
"use client";

import { Badge } from "./ui";

export function ClusterLabel({ c }: { c: any }) {
  const map: Record<string, [string, "accent" | "ok" | "neutral" | "warn"]> = {
    ready_for_fix: ["Ready for fix", "accent"], fix_proposed: ["Fix proposed", "ok"], fixed: ["Fixed", "ok"],
    correct_escalation: ["Correct escalation — no fix", "neutral"], investigate: ["Investigate", "warn"], ignored: ["Ignored", "neutral"],
  };
  if (c.label === "watching") return <Badge>{`Watching (${c.signal_count ?? c.escalations_28d ?? c.escalation_count} of ${c.min_cluster_size})`}</Badge>;
  const [text, tone] = map[c.label] ?? [c.label, "neutral"];
  return <Badge tone={tone}>{text}</Badge>;
}
