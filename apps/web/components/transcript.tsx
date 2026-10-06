// Spec: /ui/test-call.md (Layout), /ui/calls.md (Detail)
"use client";

import { CheckCircle2, Search, Wrench, XCircle } from "lucide-react";
import type { CallEvent } from "@/lib/api";
import { Badge, cx, JsonView } from "./ui";

function argsSummary(args: unknown): string {
  if (!args || typeof args !== "object") return "";
  return Object.entries(args as Record<string, unknown>).map(([k, v]) => `${k}=${String(v)}`).join(", ").slice(0, 80);
}

/** Pairs tool_call with tool_result for compact rendering. */
export function Transcript({ events, showTools = true }: { events: CallEvent[]; showTools?: boolean }) {
  const results = new Map<string, CallEvent>();
  for (const e of events) if (e.kind === "tool_result") results.set(e.data?.tool_call_id ?? `${e.data?.name}-${e.seq}`, e);
  return (
    <div className="space-y-2">
      {events.map((e) => {
        if (e.kind === "user") {
          return (
            <div key={e.seq} className="flex justify-end">
              <div className="max-w-[75%] rounded-2xl rounded-br-sm bg-accent px-3 py-2 text-sm text-white dark:text-black">{e.text}</div>
            </div>
          );
        }
        if (e.kind === "assistant") {
          return (
            <div key={e.seq} className="flex justify-start">
              <div className="max-w-[75%] rounded-2xl rounded-bl-sm bg-neutral-soft px-3 py-2 text-sm">{e.text}</div>
            </div>
          );
        }
        if (e.kind === "system") {
          return <div key={e.seq} className="text-center"><Badge tone={e.data?.category === "safety" ? "bad" : "warn"}>{e.text}</Badge></div>;
        }
        if (e.kind === "tool_call" && showTools) {
          const r = results.get(e.data?.tool_call_id) ?? events.find((x) => x.kind === "tool_result" && x.seq > e.seq && x.data?.name === e.data?.name);
          const ok = r ? r.data?.ok !== false && !r.data?.result?.error : undefined;
          const isSearch = e.data?.name === "search_knowledge";
          const top = isSearch && r?.data?.result?.results?.[0];
          return (
            <div key={e.seq} className="ml-2 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-xs">
              <div className="flex items-center gap-1.5">
                {isSearch ? <Search size={12} className="text-info" /> : <Wrench size={12} className="text-info" />}
                <span className="mono font-medium">{e.data?.name}</span>
                <span className="truncate text-muted">{argsSummary(e.data?.args)}</span>
                <span className="ml-auto">{ok === undefined ? null : ok ? <CheckCircle2 size={13} className="text-ok" /> : <XCircle size={13} className="text-bad" />}</span>
              </div>
              {isSearch && r && (
                <div className="mt-1 text-muted">{r.data?.result?.no_answer ? "No answer — the agent should offer a specialist" : top ? `${top.title} › ${top.heading} (${top.score})` : ""}</div>
              )}
              {r && <div className="mt-1"><JsonView value={r.data?.result} label="Result" /></div>}
            </div>
          );
        }
        return null;
      })}
    </div>
  );
}

export function ActivityList({ events }: { events: CallEvent[] }) {
  const calls = events.filter((e) => e.kind === "tool_call");
  if (!calls.length) return <div className="text-sm text-muted">No tool activity yet.</div>;
  return (
    <ol className="space-y-1.5">
      {calls.map((e) => {
        const r = events.find((x) => x.kind === "tool_result" && x.data?.tool_call_id === e.data?.tool_call_id) ?? events.find((x) => x.kind === "tool_result" && x.seq > e.seq);
        const ok = r ? r.data?.ok !== false && !r.data?.result?.error : undefined;
        return (
          <li key={e.seq} className={cx("flex items-center gap-2 rounded-md border border-line px-2 py-1 text-xs")}>
            {ok === undefined ? <span className="h-3 w-3 animate-pulse rounded-full bg-line" /> : ok ? <CheckCircle2 size={13} className="text-ok" /> : <XCircle size={13} className="text-bad" />}
            <span className="mono">{e.data?.name}</span>
            <span className="truncate text-muted">{argsSummary(e.data?.args)}</span>
            {r?.data?.duration_ms != null && <span className="ml-auto text-muted">{r.data.duration_ms} ms</span>}
          </li>
        );
      })}
    </ol>
  );
}
