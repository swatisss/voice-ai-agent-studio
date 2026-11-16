// Spec: /ui/agent-desk.md (Patterns), /ui/insights.md (Cluster detail)
"use client";

import { useState } from "react";
import { Badge, Button, Card, Field, Textarea, useToast } from "@/components/ui";
import { api, ApiError, useApi, useEvents } from "@/lib/api";
import { ROLE_LABEL, type StudioUser } from "@/lib/auth";
import { when } from "@/lib/format";

type Comment = { id: string; author: string; author_role: StudioUser["role"]; text: string; created_at: string };

const MIN = 10;

/** Specialist comments on an escalation pattern: evidence the fix draft reads like a resolution note (UI-80). */
export function ClusterComments({ clusterId, tenant, title = "Comments" }: { clusterId: string; tenant: string; title?: string }) {
  const toast = useToast();
  const { data, reload } = useApi<{ items: Comment[] }>(`/api/insights/clusters/${clusterId}/comments`, [tenant, clusterId]);
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEvents(["insights"], (e) => { if (e.type === "cluster.updated" && e.data?.id === clusterId) reload(); }, tenant);

  async function add() {
    if (text.trim().length < MIN) { setErr(`Write at least ${MIN} characters.`); return; }
    setBusy(true);
    try {
      await api(`/api/insights/clusters/${clusterId}/comments`, { method: "POST", json: { text } });
      setText(""); setErr(null);
      reload();
    } catch (e) { toast((e as ApiError).detail, "bad"); }
    finally { setBusy(false); }
  }

  return (
    <Card title={title}>
      <div className="space-y-4">
        {!data?.items.length ? <p className="text-sm text-muted">No comments yet.</p> : (
          <ul className="space-y-2">
            {data.items.map((c) => (
              <li key={c.id} className="rounded-lg border border-line px-3 py-2 text-sm">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="font-medium">{c.author}</span><Badge>{ROLE_LABEL[c.author_role] ?? c.author_role}</Badge>
                  <span className="ml-auto text-xs text-muted">{when(c.created_at)}</span>
                </div>
                <p className="mt-1 whitespace-pre-wrap">{c.text}</p>
              </li>
            ))}
          </ul>
        )}
        <Field label="What do you tell callers about this?" error={err} hint="Comments are used as evidence when the agent's fix is drafted.">
          <Textarea value={text} maxLength={1000} onChange={(e) => { setText(e.target.value); setErr(null); }} />
        </Field>
        <Button variant="primary" loading={busy} onClick={add}>Add comment</Button>
      </div>
    </Card>
  );
}
