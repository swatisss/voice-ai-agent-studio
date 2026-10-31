// Spec: /ui/dashboard.md (Self-learning card), /ui/insights.md (Learning inbox), /architecture/self-learning.md
"use client";

import Link from "next/link";
import { useState } from "react";
import { api, type ApiError, useApi, useEvents } from "@/lib/api";
import { label, when } from "@/lib/format";
import { Badge, Button, Card, Spinner, useToast } from "./ui";

type Run = { id: string; trigger: string; status: string; summary: { totals?: Record<string, number> }; started_at: string; finished_at: string | null };
type Proposal = {
  id: string; cluster_id: string; cluster_name: string | null; kind: string; origin: string; title: string; rationale: string; created_at: string;
  eval_summary: { gate?: { passed: boolean; reasons: string[] }; lift_pct?: number; held_out_cases?: number; held_out_candidate_pass?: number;
    regression_cases?: number; regression_pass?: number } | null;
};

const SIGNALS: [string, string][] = [["escalated", "escalated"], ["thumbs_down", "thumbs down"], ["no_answer", "unanswered searches"],
  ["tool_error", "tool errors"], ["hard_fail", "hard fails"], ["calibrated_judge_fail", "failed checks"]];

/** Last run, waiting proposals and Run now, kept fresh by `learning.run.finished` and proposal events. */
function useLearning(tenant: string) {
  const toast = useToast();
  const runs = useApi<{ items: Run[] }>("/api/learning/runs", [tenant]);
  const inbox = useApi<{ items: Proposal[] }>("/api/insights/inbox", [tenant]);
  const [starting, setStarting] = useState(false);
  useEvents(["insights"], (e) => {
    if (e.type === "learning.run.finished") { runs.reload(); inbox.reload(); }
    if (e.type === "proposal.updated" || e.type === "proposal.approved") inbox.reload();
  }, tenant);
  const running = runs.data?.items.some((r) => r.status === "running") ?? false;
  async function runNow() {
    setStarting(true);
    try {
      await api("/api/learning/run", { method: "POST" });
      runs.reload();
    } catch (e) {
      toast((e as ApiError).detail, "bad");
    } finally {
      setStarting(false);
    }
  }
  const last = runs.data?.items.find((r) => r.status !== "running");
  return { runs: runs.data, inbox: inbox.data, running: running || starting, runNow, last };
}

function Counts({ run }: { run: Run }) {
  const t = run.summary.totals ?? {};
  const signals = SIGNALS.map(([k, text]) => [t[`signals.${k}`] ?? 0, text] as const).filter(([n]) => n > 0);
  return (
    <span>
      {t.calls_reviewed ?? 0} calls reviewed{signals.length ? ` · ${signals.map(([n, text]) => `${n} ${text}`).join(", ")}` : " · no signals"}
      {" "}· {t.drafted ?? 0} proposal{t.drafted === 1 ? "" : "s"} drafted, {t.passed ?? 0} passed the check
      {(t.failed_drafts ?? 0) > 0 && <span className="text-bad"> · {t.failed_drafts} draft{t.failed_drafts === 1 ? "" : "s"} failed</span>}
    </span>
  );
}

/** UI-55: the dashboard's trigger for the loop, so a demo can run it on the spot. */
export function LearningCard({ tenant }: { tenant: string }) {
  const { runs, inbox, running, runNow, last } = useLearning(tenant);
  const waiting = inbox?.items.length ?? 0;
  return (
    <Card title="Self-learning" actions={<Button variant="primary" onClick={runNow} disabled={running} loading={running}>{running ? "Learning…" : "Run learning now"}</Button>}>
      {!runs ? <Spinner /> : (
        <div className="space-y-2 text-sm">
          <p className="text-muted">Runs every night at 02:00 UTC: reviews each agent's calls, drafts fixes to knowledge, tools and rules, and checks them against the current version. Nothing changes until someone approves it.</p>
          {last ? (
            <div><span className="font-medium">Last run {when(last.finished_at ?? last.started_at)}</span>{last.status === "failed" ? <Badge className="ml-2" tone="bad">Failed</Badge> : <>: <Counts run={last} /></>}</div>
          ) : <div className="text-muted">No run yet.</div>}
          <div className="flex items-center gap-3">
            <Badge tone={waiting ? "accent" : "neutral"}>{waiting} waiting for review</Badge>
            <Link className="font-medium text-accent" href="/insights/#inbox">Review proposals</Link>
          </div>
        </div>
      )}
    </Card>
  );
}

/** UI-54: Last night strip and the learning inbox at the top of Insights. */
export function LearningInbox({ tenant }: { tenant: string }) {
  const { inbox, running, runNow, last } = useLearning(tenant);
  return (
    <div id="inbox" className="space-y-3 scroll-mt-4">
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-panel px-4 py-3 text-sm">
        <span className="font-medium">Last night</span>
        {last ? <span className="text-muted">{when(last.finished_at ?? last.started_at)} · <Counts run={last} /></span> : <span className="text-muted">No run yet — learning runs every night at 02:00 UTC.</span>}
        <Button className="ml-auto" onClick={runNow} disabled={running} loading={running}>{running ? "Learning…" : "Run now"}</Button>
      </div>
      <Card title={`Waiting for review${inbox ? ` (${inbox.items.length})` : ""}`}>
        {!inbox ? <Spinner /> : inbox.items.length === 0 ? (
          <div className="text-sm text-muted">Nothing waiting. Proposals drafted overnight appear here.</div>
        ) : (
          <ul className="space-y-2">
            {inbox.items.map((p) => {
              const s = p.eval_summary;
              const regressed = s ? (s.regression_cases ?? 0) - (s.regression_pass ?? 0) : 0;
              return (
                <li key={p.id} className="rounded-lg border border-line p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={p.origin === "nightly" ? "accent" : "neutral"}>{p.origin === "nightly" ? "Nightly" : "Manual"}</Badge>
                    <Badge tone="info">{label(p.kind)}</Badge>
                    <span className="font-medium">{p.title}</span>
                    {s?.gate ? <Badge tone={s.gate.passed ? "ok" : "bad"}>{s.gate.passed ? "Passed" : "Failed"}</Badge> : <Badge>Not checked</Badge>}
                    <Link className="ml-auto text-sm font-medium text-accent" href={`/insights/cluster/?id=${p.cluster_id}`}>Open</Link>
                  </div>
                  <div className="mt-1 text-sm text-muted">{p.cluster_name} · {p.rationale}</div>
                  {s && (
                    <div className="mt-1 text-xs text-muted">
                      Lift {(s.lift_pct ?? 0) >= 0 ? "+" : ""}{s.lift_pct ?? 0} pts{s.held_out_cases ? ` · held out ${s.held_out_candidate_pass}/${s.held_out_cases}` : ""} · {regressed ? `${regressed} regressed` : "no regressions"}
                      {s.gate && !s.gate.passed && <span className="text-bad"> · {s.gate.reasons.join("; ")}</span>}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </div>
  );
}
