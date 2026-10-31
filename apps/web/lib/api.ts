// Spec: /ui/app-shell.md (API client), /api/rest-api.md, /api/events.md
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export class ApiError extends Error {
  constructor(public status: number, public error: string, public detail: string) {
    super(detail || error);
  }
}

let currentTenant = "";
export function setApiTenant(t: string) { currentTenant = t; }
export function getApiTenant() { return currentTenant; }

export async function api<T = any>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (currentTenant) headers["X-Tenant-Id"] = currentTenant;
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers, body });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data.error ?? "error", data.detail ?? res.statusText);
  return data as T;
}

/** Fetch on mount and when deps/tenant change. */
export function useApi<T = any>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const reload = useCallback(async () => {
    if (!path || !currentTenant) return;
    setLoading(true);
    try {
      setData(await api<T>(path));
      setError(null);
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, currentTenant, ...deps]);
  useEffect(() => { reload(); }, [reload]);
  return { data, error, loading, reload, setData };
}

export type BusEvent = { id: string; topic: string; type: string; at: string; data: any };

/** Subscribe to SSE topics for the current tenant; reconnects with backoff. */
export function useEvents(topics: string[], handler: (e: BusEvent) => void, tenant: string) {
  const ref = useRef(handler);
  ref.current = handler;
  const key = topics.filter(Boolean).join(",");
  useEffect(() => {
    if (!tenant || !key) return;
    let es: EventSource | null = null;
    let closed = false;
    let delay = 1000;
    const open = () => {
      es = new EventSource(`${API_BASE}/api/events?tenant=${encodeURIComponent(tenant)}&topics=${encodeURIComponent(key)}`);
      es.onopen = () => { delay = 1000; };
      es.onmessage = () => undefined;
      const types = ["call.event", "call.escalated", "call.ended", "escalation.created", "escalation.updated", "analysis.created",
        "cluster.updated", "proposal.updated", "eval.progress", "proposal.approved", "agent.published", "scorecard.updated", "test_run.progress", "test_run.finished"];
      for (const t of types) es.addEventListener(t, (ev) => { try { ref.current(JSON.parse((ev as MessageEvent).data)); } catch { /* ignore */ } });
      es.onerror = () => {
        es?.close();
        if (!closed) setTimeout(open, (delay = Math.min(delay * 2, 15000)));
      };
    };
    open();
    return () => { closed = true; es?.close(); };
  }, [key, tenant]);
}

// ----------------------------------------------------------------- shared types
export type CallEvent = { seq: number; at?: string; kind: string; text: string | null; data: any };
export type Packet = {
  summary: string; intent: string; entities: Record<string, unknown>; already_tried: string[];
  escalation_reason: { category: string; detail: string };
  sentiment: { start: string; end: string; trend: string }; suggested_next_action: string; caller_verified: boolean;
};
export type Escalation = {
  id: string; call_id: string; status: string; reason_category: string; reason_detail: string;
  packet_status: string; packet: Packet | null; assignee: string | null; disposition: string | null;
  resolution_note: string | null; created_at: string; accepted_at: string | null; resolved_at: string | null; call?: any;
};

// Spec: /architecture/agent-memory.md (Memory item), /ui/member-memory.md
export type MemoryItem = {
  id: string; agent_id: string; member_ref: string; kind: "episode" | "fact"; category: string; text: string;
  status: "active" | "retired"; valid_at: string; invalid_at: string | null; superseded_by: string | null; expires_at: string;
  source_call_id: string | null; source_seq: number | null; created_at: string; updated_at: string;
};
export type MemoryEvent = {
  id: string; agent_id: string | null; member_ref: string; memory_id: string | null;
  action: "added" | "superseded" | "confirmed" | "restored" | "expired" | "erased"; actor: "agent" | "studio" | "system";
  call_id: string | null; text_before: string | null; text_after: string | null; reason: string | null; at: string;
};
export type MemberMemory = {
  member_ref: string; first_name: string | null; agents: { id: string; name: string }[];
  facts: MemoryItem[]; episodes: MemoryItem[]; retired: MemoryItem[]; events: MemoryEvent[];
};

// Spec: /architecture/call-scoring.md (Scorecard)
export type Verdict = "pass" | "fail" | "n/a" | "unknown" | "not_judged";
export type CheckGroup = "outcome" | "responsiveness" | "knowledge" | "tools" | "memory" | "safety";
export type ScoreCheck = {
  key: string; group: CheckGroup; method: "code" | "judge"; hard_gate: boolean; text: string; source: "built_in" | "config" | "custom";
  verdict: Verdict; reason: string; evidence: { seqs: number[]; chunk_ids: string[] };
};
export type CheckReview = { check_key: string; verdict: "pass" | "fail" | "n/a"; judge_verdict: Verdict; note: string; reviewer: string; at: string };
export type Scorecard = {
  id: string; call_id: string; agent_version_id: string; measures: Record<string, any>; checks: ScoreCheck[]; hard_fail: boolean;
  score: number | null; judged: boolean; judge_model: string | null; source: "llm" | "seed"; updated_at: string;
  reviews: Record<string, CheckReview>;
};

// Spec: /architecture/test-suites.md (Scenario, Test run)
export type Persona = "calm" | "confused" | "impatient" | "adversarial";
export type Scenario = {
  id: string; name: string; caller_goal: string; caller_profile: Record<string, string>; persona: Persona;
  expected: "resolved" | "escalated"; required_tools: { name: string; args: Record<string, string> }[]; forbidden_tools: string[];
  expected_results: { tool: string; field: string; equals: string }[]; memory: string[]; enabled: boolean;
  last?: { eval_run_id: string; passed: number; of: number } | null;
};
export type TestRunSummary = {
  scenarios: number; repeats: number; pass_all: number; pass_any: number; pass_rate: number | null; hard_fails: number;
  check_pass_rates: Record<string, number | null>; by_scenario: Record<string, { passed: number; of: number }>;
  duration_s: number; pipeline: string; fidelity: "faithful" | "text_approximation";
};
export type TestRun = {
  id: string; target: "published" | "draft" | "version"; version: number | null; version_id: string | null;
  trigger: "manual" | "builder" | "publish"; status: "running" | "done" | "failed"; repeats: number;
  summary: Partial<TestRunSummary>; error: string | null; created_at: string; finished_at: string | null;
};
export type TestResult = {
  scenario_id: string | null; scenario: Scenario | null; repeat: number; passed: boolean; failures: string[]; call_id: string | null;
  scorecard: { score: number | null; hard_fail: boolean; failed_checks: string[] } | null;
};

/** GET a JSON resource and save it as a file in the browser. */
export async function downloadJson(path: string, filename: string): Promise<void> {
  const data = await api(path);
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
