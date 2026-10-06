// Spec: /ui/agent-builder.md (Agents list)
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useTenant } from "@/components/shell";
import { Badge, Button, EmptyState, Field, Input, Modal, Spinner, Textarea, useToast } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { when } from "@/lib/format";

export default function AgentsPage() {
  const { tenant } = useTenant();
  const { data } = useApi<{ items: any[] }>("/api/agents", [tenant]);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const router = useRouter();
  const toast = useToast();

  async function create() {
    setSaving(true);
    try {
      const a = await api("/api/agents", { method: "POST", json: { name, description } });
      router.push(`/agents/edit/?id=${a.id}`);
    } catch (e) {
      toast((e as ApiError).detail, "bad");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Agents</h1>
        <Button variant="primary" onClick={() => setOpen(true)}>New agent</Button>
      </div>
      {!data ? <Spinner /> : data.items.length === 0 ? (
        <EmptyState title="No agents yet">Create an agent, add knowledge, tools and skills, then publish it.</EmptyState>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {data.items.map((a) => (
            <div key={a.id} className="rounded-xl border border-line bg-panel p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-medium">{a.name}</div>
                  <div className="text-sm text-muted">{a.description}</div>
                </div>
                {a.published_version ? <Badge tone="ok">v{a.published_version.version}</Badge> : <Badge>Not published</Badge>}
              </div>
              <div className="mt-3 flex items-center gap-2">
                <Link href={`/agents/edit/?id=${a.id}`}><Button>Open</Button></Link>
                <Link href={`/test-call/?agent=${a.id}`}><Button variant="ghost" disabled={!a.published_version}>Test</Button></Link>
                <span className="ml-auto text-xs text-muted">Updated {when(a.updated_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
      <Modal open={open} title="New agent" onClose={() => setOpen(false)}
        footer={<><Button onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" loading={saving} disabled={!name.trim()} onClick={create}>Create</Button></>}>
        <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Billing Agent" /></Field>
        <Field label="Description"><Textarea value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
      </Modal>
    </div>
  );
}
