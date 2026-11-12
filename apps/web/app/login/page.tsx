// Spec: /ui/app-shell.md (Sign-in)
"use client";

import { AudioWaveform } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Button, Field, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

const ACCOUNTS = [
  { email: "admin@echomind.test", label: "Admin: publishes agents and approves fixes" },
  { email: "reviewer@echomind.test", label: "Reviewer: works escalations, answers and reviews" },
];

/** Only paths inside the Studio are followed after sign-in. */
function nextPath(): string {
  const next = new URLSearchParams(window.location.search).get("next") ?? "/";
  return next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/login") ? next : "/";
}

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/auth/login", { method: "POST", json: { email, password } });
      window.location.href = nextPath();
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? "Email or password is wrong" : "Could not sign in. Is the API running?");
      setBusy(false);
    }
  }

  return (
    <main id="main" className="flex min-h-screen items-center justify-center bg-bg p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-2xl border border-line bg-panel p-6 shadow-[var(--shadow)]">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent text-on-accent"><AudioWaveform size={22} aria-hidden="true" /></span>
          <span className="leading-tight">
            <span className="block text-lg font-semibold">Echo Mind</span>
            <span className="block text-xs text-muted">Voice Agent Studio</span>
          </span>
        </div>
        <h1 className="text-xl font-semibold">Sign in</h1>
        <Field label="Email">
          <Input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </Field>
        <Field label="Password">
          <Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </Field>
        {error && <p className="text-sm text-bad" role="alert">{error}</p>}
        <Button variant="primary" type="submit" loading={busy} className="w-full">Sign in</Button>
        <div className="rounded-xl bg-accent-soft p-3 text-xs">
          <p className="mb-1 font-semibold">Demo accounts</p>
          <ul className="space-y-1">
            {ACCOUNTS.map((a) => (
              <li key={a.email}>
                <button type="button" className="font-mono text-accent underline" onClick={() => setEmail(a.email)}>{a.email}</button>
                <span className="block text-muted">{a.label}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-muted">Passwords are set in <code>apps/api/.env</code>.</p>
        </div>
      </form>
    </main>
  );
}
