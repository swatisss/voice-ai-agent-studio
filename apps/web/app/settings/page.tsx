// Spec: /ui/settings.md
"use client";

import { useState } from "react";
import { useTenant } from "@/components/shell";
import { Button, Card, Field, Input, Spinner, useToast } from "@/components/ui";
import { api, ApiError, useApi } from "@/lib/api";
import { ago } from "@/lib/format";

type TenantSettings = {
  allowed_pipelines: string[];
  openai: { key_set: boolean; key_last4: string | null; key_updated_at: string | null; platform_fallback: boolean };
};

export default function SettingsPage() {
  const { tenant } = useTenant();
  const toast = useToast();
  const { data, setData } = useApi<TenantSettings>("/api/tenant-settings", [tenant]);
  const [inUse, setInUse] = useState<string | null>(null);
  const [key, setKey] = useState("");
  const [keyError, setKeyError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function put(body: Record<string, unknown>) {
    setInUse(null);
    try {
      setData(await api<TenantSettings>("/api/tenant-settings", { method: "PUT", json: body }));
    } catch (e) {
      const err = e as ApiError;
      if (err.error === "pipeline_in_use") setInUse(err.detail);
      else toast(err.detail, "bad");
    }
  }

  async function saveKey() {
    setSaving(true);
    setKeyError(null);
    try {
      const openai = await api<Partial<TenantSettings["openai"]>>("/api/tenant-settings/openai-key", { method: "PUT", json: { api_key: key } });
      setKey("");
      if (data) setData({ ...data, openai: { ...data.openai, ...openai } });
    } catch (e) {
      const err = e as ApiError;
      setKeyError(err.error === "secrets_unavailable" ? "Key storage is not configured on this server (TENANT_SECRETS_KEY)." : err.detail);
    } finally {
      setSaving(false);
    }
  }

  async function removeKey() {
    await api("/api/tenant-settings/openai-key", { method: "DELETE" });
    if (data) setData({ ...data, openai: { ...data.openai, key_set: false, key_last4: null, key_updated_at: null } });
  }

  if (!data) return <Spinner />;
  const realtime = data.allowed_pipelines.includes("realtime");
  const { openai } = data;
  const status = openai.key_set
    ? `Own key ending in ••••${openai.key_last4}, saved ${openai.key_updated_at ? ago(openai.key_updated_at) : ""}`
    : openai.platform_fallback ? "Using the platform key" : "No key - realtime calls are unavailable";

  return (
    <div className="space-y-5">
      <h1>Settings</h1>
      <p className="max-w-3xl text-muted">Settings for the selected business unit. They apply to all of its agents.</p>
      <Card title="Voice pipelines">
        <ul className="max-w-3xl space-y-3 text-sm">
          <li className="flex items-center gap-3"><input type="checkbox" role="switch" checked disabled aria-label="Cascade" className="h-4 w-4 accent-[var(--accent)]" />Cascade (always on)</li>
          <li>
            <label className="flex items-center gap-3 font-medium">
              <input type="checkbox" role="switch" className="h-4 w-4 accent-[var(--accent)]" checked={realtime}
                onChange={(e) => put({ allowed_pipelines: e.target.checked ? ["cascade", "realtime"] : ["cascade"] })} />
              Allow realtime speech-to-speech
            </label>
            <p className="ml-7 mt-1 text-muted">One OpenAI model listens and speaks: lower delay, higher cost per minute, less control over exact wording.</p>
          </li>
        </ul>
        {inUse && <p role="alert" className="mt-3 text-sm text-bad">Switch these agents to Cascade and publish them first: {inUse}</p>}
      </Card>
      <Card title="OpenAI key">
        <p className="mb-3 max-w-3xl text-sm text-muted">Used only for realtime speech-to-speech calls. The key is stored encrypted and cannot be shown again.</p>
        <p className="mb-3 text-sm font-medium" data-testid="key-status">{status}</p>
        <div className="flex max-w-xl flex-wrap items-end gap-2">
          <div className="min-w-64 flex-1">
            <Field label={openai.key_set ? "Replace key" : "API key"} error={keyError}>
              <Input type="password" autoComplete="off" value={key} placeholder="sk-…" onChange={(e) => setKey(e.target.value)} />
            </Field>
          </div>
          <Button variant="primary" loading={saving} disabled={!key.trim()} onClick={saveKey}>Save key</Button>
          {openai.key_set && <Button variant="ghost" onClick={removeKey}>Remove key</Button>}
        </div>
        <label className="mt-4 flex items-center gap-3 text-sm">
          <input type="checkbox" role="switch" className="h-4 w-4 accent-[var(--accent)]" checked={openai.platform_fallback}
            onChange={(e) => put({ openai_platform_fallback: e.target.checked })} />
          Use the platform key when this unit has none
        </label>
      </Card>
    </div>
  );
}
