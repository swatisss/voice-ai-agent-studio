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
        "cluster.updated", "proposal.updated", "eval.progress", "proposal.approved", "agent.published"];
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
