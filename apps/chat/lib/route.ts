// Spec: /architecture/external-chat-app.md (Server routes, Failure behavior)
import { NextResponse } from "next/server";
import { ChatError, readConfig, type Config } from "./platform.ts";

/** Runs a handler with the config, or answers 503 `chat_not_configured` (CHAT-03); maps upstream errors for the browser. */
export async function guarded(run: (cfg: Config) => Promise<unknown>): Promise<NextResponse> {
  const cfg = readConfig();
  if (!cfg) return NextResponse.json({ error: "chat_not_configured", detail: "The chat is not configured on this server." }, { status: 503 });
  try {
    return NextResponse.json(await run(cfg));
  } catch (e) {
    if (e instanceof ChatError) {
      const headers: Record<string, string> = e.retryAfter ? { "Retry-After": String(e.retryAfter) } : {};
      return NextResponse.json({ error: e.code, detail: e.message }, { status: e.status, headers });
    }
    console.error("chat-app: unexpected error", e);
    return NextResponse.json({ error: "upstream_unavailable", detail: "We can't reach the assistant. Try again." }, { status: 502 });
  }
}
