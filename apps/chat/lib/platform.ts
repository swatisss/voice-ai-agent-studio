// Spec: /architecture/external-chat-app.md
// Server-side only: talks to the platform's public /v1 API with the member key. Nothing here is imported by the browser.
// Plain functions with an injectable fetch, so tests run against a stub platform.

export type Config = { apiUrl: string; tenant: string; key: string; brand: string };

export type Item = { id: string; speaker: "caller" | "front_desk" | "agent" | "human"; text: string; at: string; author?: string };
export type Escalation = { id: string; status: "waiting" | "accepted" | "resolved"; assignee: string | null } | null;
export type View = { conversation_id: string; status: "active" | "escalated" | "ended"; escalation: Escalation; items: Item[]; cursor: string | null };

type Fetch = typeof fetch;

/** An upstream failure, already mapped to what the browser may see (never the upstream body, URL or key). */
export class ChatError extends Error {
  status: number;
  code: string;
  retryAfter?: number;
  constructor(status: number, code: string, message: string, retryAfter?: number) {
    super(message);
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

export function readConfig(env: Record<string, string | undefined> = process.env): Config | null {
  const key = (env.VOICEAI_API_KEY ?? "").trim();
  if (!key) return null;
  return {
    apiUrl: (env.VOICEAI_API_URL || "http://localhost:8000").replace(/\/+$/, ""),
    tenant: env.VOICEAI_TENANT_ID || "northgate-health",
    key,
    brand: env.CHAT_BRAND_NAME || "Northgate Health",
  };
}

async function call(cfg: Config, f: Fetch, method: string, path: string, body?: unknown): Promise<any> {
  let res: Response;
  try {
    res = await f(`${cfg.apiUrl}/v1/tenants/${encodeURIComponent(cfg.tenant)}${path}`, {
      method,
      headers: { Authorization: `Bearer ${cfg.key}`, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    throw new ChatError(502, "upstream_unavailable", "We can't reach the assistant. Try again.");
  }
  if (res.ok) return res.json();
  const detail = await res.json().catch(() => ({}));
  if (res.status === 429) throw new ChatError(429, "rate_limited", "One moment, please.", Number(res.headers.get("retry-after")) || 3);
  if (res.status === 404) throw new ChatError(404, "conversation_not_found", "This chat is no longer available.");
  if (res.status === 409 && detail?.error === "conversation_ended") throw new ChatError(409, "conversation_ended", "This chat has ended.");
  if (res.status === 401) console.error("chat-app: the platform refused the API key (revoked or wrong)");  // never shown to the page
  throw new ChatError(502, "upstream_unavailable", "We can't reach the assistant. Try again.");
}

function view(conversationId: string, thread: any): View {
  return { conversation_id: conversationId, status: thread.status, escalation: thread.escalation ?? null, items: thread.items ?? [], cursor: thread.cursor ?? null };
}

export async function poll(cfg: Config, id: string, cursor?: string | null, f: Fetch = fetch): Promise<View> {
  const q = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  return view(id, await call(cfg, f, "GET", `/conversations/${encodeURIComponent(id)}/messages${q}`));
}

/** CHAT-02: one conversation through POST /v1/.../conversations; the thread comes back from the same poll the page keeps using. */
export async function start(cfg: Config, message?: string, f: Fetch = fetch, rand: () => string = () => crypto.randomUUID()): Promise<View> {
  const created = await call(cfg, f, "POST", "/conversations", {
    channel: "text",
    ...(message?.trim() ? { message: message.trim() } : {}),
    external_id: `web-${rand()}`,
    metadata: { source: "chat-app" },
  });
  return poll(cfg, created.conversation_id, null, f);
}

/** Sends a line (the AI answers, or the line is stored for the specialist), then returns what is new since `cursor`. */
export async function send(cfg: Config, id: string, text: string, cursor?: string | null, f: Fetch = fetch): Promise<View> {
  await call(cfg, f, "POST", `/conversations/${encodeURIComponent(id)}/messages`, { text });
  return poll(cfg, id, cursor, f);
}

export async function end(cfg: Config, id: string, f: Fetch = fetch): Promise<void> {
  await call(cfg, f, "POST", `/conversations/${encodeURIComponent(id)}/end`);
}
