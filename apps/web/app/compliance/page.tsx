// Spec: /ui/compliance.md, /product/compliance-evidence.md
"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Badge, Card, Spinner } from "@/components/ui";
import { useApi } from "@/lib/api";
import { ago } from "@/lib/format";
import type { Tone } from "@/lib/format";

type Evidence = { id: string; status: "passed" | "failed" | "not_run" | "no_test"; tests: string[] };
type Control = {
  id: string; rule: string; reference: string; enforcement: string; where: string;
  status: "passed" | "failed" | "not_run" | "process"; evidence: Evidence[];
};
type Report = { controls: Control[]; gaps: string[]; report: { generated_at: string; commit: string } | null };

const STATUS: Record<string, { text: string; tone: Tone }> = {
  passed: { text: "Passed", tone: "ok" }, failed: { text: "Failed", tone: "bad" },
  not_run: { text: "Not run", tone: "neutral" }, no_test: { text: "No test", tone: "warn" }, process: { text: "Process", tone: "info" },
};
const ENFORCEMENT: Record<string, string> = { code: "Code", "prompt and score": "Prompt & score", process: "Process" };

export default function CompliancePage() {
  const { data } = useApi<Report>("/api/compliance/evidence");
  const [open, setOpen] = useState<string | null>(null);
  if (!data) return <Spinner />;
  const withTests = data.controls.filter((c) => c.status !== "process");
  const passing = withTests.filter((c) => c.status === "passed").length;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Compliance evidence</h1>
        <p className="text-sm text-muted">
          Each control is enforced by the platform and proven by tests. Regulation references show what a control supports; they are not a legal opinion.
        </p>
        <p className="mt-2 text-sm" aria-label="Test report">
          {data.report
            ? <>Tests run {ago(data.report.generated_at)}{data.report.commit && <> on commit <span className="mono">{data.report.commit}</span></>}: <strong>{passing} of {withTests.length}</strong> controls passing</>
            : <>No test report yet. Run <code className="mono">python scripts/compliance_check.py</code>.</>}
        </p>
      </div>

      <Card title="Controls">
        <ul className="divide-y divide-line">
          {data.controls.map((c) => {
            const expanded = open === c.id;
            const st = STATUS[c.status];
            return (
              <li key={c.id} className="py-3">
                <button className="flex w-full flex-wrap items-start gap-x-3 gap-y-1 text-left" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : c.id)}>
                  <span className="mt-0.5 text-muted">{expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}</span>
                  <span className="mono w-8 shrink-0 text-sm font-semibold">{c.id}</span>
                  <span className="min-w-0 flex-1 basis-64 text-sm">
                    {c.rule}
                    <span className="block text-xs text-muted">{c.reference}</span>
                  </span>
                  <Badge tone="neutral">{ENFORCEMENT[c.enforcement] ?? c.enforcement}</Badge>
                  <Badge tone={st.tone}>{st.text}</Badge>
                </button>
                {expanded && (
                  <div className="mt-2 space-y-2 pl-12 text-sm">
                    <p className="text-muted">Enforced in: {c.where}</p>
                    {c.evidence.length === 0 ? <p className="text-muted">Kept by process; no automated test.</p> : (
                      <ul className="space-y-1">
                        {c.evidence.map((e) => (
                          <li key={e.id} className="flex flex-wrap items-start gap-2">
                            <span className="mono w-20 shrink-0">{e.id}</span>
                            <Badge tone={STATUS[e.status].tone}>{STATUS[e.status].text}</Badge>
                            <span className="mono min-w-0 flex-1 basis-60 break-all text-xs text-muted">{e.tests.join(", ")}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </Card>

      <Card title="Not yet in place">
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {data.gaps.map((g) => <li key={g}>{g}</li>)}
        </ul>
      </Card>
    </div>
  );
}
