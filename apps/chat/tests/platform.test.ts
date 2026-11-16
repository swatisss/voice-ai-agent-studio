// Spec: /architecture/external-chat-app.md
// Covers: CHAT-01, CHAT-02, CHAT-03, CHAT-04, CHAT-06
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { ChatError, end, poll, readConfig, send, start } from "../lib/platform.ts";

const cfg = { apiUrl: "http://platform.test", tenant: "northgate-health", key: "vak_" + "x".repeat(40), brand: "Northgate Health" };

type Seen = { url: string; method: string; headers: Record<string, string>; body?: any };

/** A stub platform: answers by method and path, records every request. */
function stub(answer: (s: Seen) => Response) {
  const seen: Seen[] = [];
  const f = (async (input: any, init: any) => {
    const s: Seen = { url: String(input), method: init?.method ?? "GET", headers: init?.headers ?? {}, body: init?.body ? JSON.parse(init.body) : undefined };
    seen.push(s);
    return answer(s);
  }) as typeof fetch;
  return { f, seen };
}
const json = (body: unknown, status = 200, headers: Record<string, string> = {}) => new Response(JSON.stringify(body), { status, headers });
const thread = (over: Record<string, unknown> = {}) => ({ status: "active", escalation: null, cursor: "c1", items: [{ id: "a", speaker: "front_desk", text: "Hi, I'm a virtual assistant", at: "2026-11-16T10:00:00Z" }], ...over });

test("CHAT-03: no key means not configured", () => {
  assert.equal(readConfig({}), null);
  assert.equal(readConfig({ VOICEAI_API_KEY: "   " }), null);
  const c = readConfig({ VOICEAI_API_KEY: "vak_abc", VOICEAI_API_URL: "http://x:9/" });
  assert.deepEqual([c?.apiUrl, c?.tenant, c?.brand], ["http://x:9", "northgate-health", "Northgate Health"]);
});

test("CHAT-02 and CHAT-01: start creates one text conversation on a /v1 path with the bearer key", async () => {
  const { f, seen } = stub((s) => (s.method === "POST" ? json({ conversation_id: "conv1" }, 201) : json(thread())));
  const v = await start(cfg, "I want to check on a claim", f, () => "r1");
  assert.equal(seen[0].method, "POST");
  assert.equal(seen[0].url, "http://platform.test/v1/tenants/northgate-health/conversations");
  assert.deepEqual(seen[0].body, { channel: "text", message: "I want to check on a claim", external_id: "web-r1", metadata: { source: "chat-app" } });
  assert.ok(seen.every((s) => s.url.includes("/v1/tenants/") && s.headers.Authorization === `Bearer ${cfg.key}`));
  assert.equal(v.conversation_id, "conv1");
  assert.match(v.items[0].text, /virtual assistant/i);
  assert.ok(!JSON.stringify(v).includes(cfg.key));
});

test("CHAT-04: polls follow the escalation from waiting to accepted to ended", async () => {
  const states = [
    thread({ status: "escalated", escalation: { id: "e1", status: "waiting", assignee: null } }),
    thread({ status: "escalated", escalation: { id: "e1", status: "accepted", assignee: "Sam" }, items: [{ id: "b", speaker: "human", text: "Hi, Sam here", at: "2026-11-16T10:05:00Z", author: "Sam" }] }),
    thread({ status: "ended", escalation: { id: "e1", status: "resolved", assignee: "Sam" }, items: [] }),
  ];
  let n = 0;
  const { f, seen } = stub(() => json(states[n++]));
  const a = await poll(cfg, "conv1", null, f);
  const b = await poll(cfg, "conv1", "c1", f);
  const c = await poll(cfg, "conv1", "c2", f);
  assert.equal(a.escalation?.status, "waiting");
  assert.deepEqual([b.escalation?.assignee, b.items[0].speaker, b.items[0].author], ["Sam", "human", "Sam"]);
  assert.equal(c.status, "ended");
  assert.ok(seen[1].url.endsWith("/conversations/conv1/messages?cursor=c1"));
});

test("send posts the line, then returns what is new since the cursor", async () => {
  const { f, seen } = stub((s) => (s.method === "POST" ? json({ status: "active" }) : json(thread())));
  await send(cfg, "conv1", "hello", "c0", f);
  assert.deepEqual([seen[0].method, seen[0].body], ["POST", { text: "hello" }]);
  assert.ok(seen[1].url.endsWith("?cursor=c0"));
});

test("CHAT-06: 429 keeps Retry-After; 5xx and a dead platform become the friendly message; 404 and 409 map", async () => {
  const run = async (answer: () => Response) => { try { await poll(cfg, "x", null, stub(answer).f); } catch (e) { return e as ChatError; } };
  const limited = await run(() => json({ error: "rate_limited" }, 429, { "Retry-After": "3" }));
  assert.deepEqual([limited?.status, limited?.code, limited?.retryAfter], [429, "rate_limited", 3]);
  const down = await run(() => json({ error: "boom", detail: "secret upstream trace" }, 503));
  assert.deepEqual([down?.status, down?.code], [502, "upstream_unavailable"]);
  assert.ok(!down?.message.includes("secret"));
  const refused = await poll(cfg, "x", null, (async () => { throw new Error("ECONNREFUSED http://platform.test"); }) as typeof fetch).then(() => null, (e) => e as ChatError);
  assert.deepEqual([refused?.status, refused?.message.includes("platform.test")], [502, false]);
  assert.equal((await run(() => json({}, 404)))?.code, "conversation_not_found");
  assert.equal((await run(() => json({ error: "conversation_ended" }, 409)))?.code, "conversation_ended");
  const unauthorised = await run(() => json({ error: "invalid_key" }, 401));
  assert.equal(unauthorised?.code, "upstream_unavailable");  // the page never names a revoked key
});

test("end posts to the end route", async () => {
  const { f, seen } = stub(() => json({ status: "ended" }));
  await end(cfg, "conv1", f);
  assert.equal(seen[0].url, "http://platform.test/v1/tenants/northgate-health/conversations/conv1/end");
});

test("CHAT-01: browser code never reads the environment or the key", () => {
  const browser = [join(import.meta.dirname, "..", "components")];
  for (const dir of browser) for (const name of readdirSync(dir)) {
    const code = readFileSync(join(dir, name), "utf8");
    assert.ok(!/process\.env|cfg\.key|platform\.ts/.test(code), `${name} must not touch server-only code`);
  }
  const page = readFileSync(join(import.meta.dirname, "..", "app", "page.tsx"), "utf8");
  assert.ok(!/key=|\.key\b/.test(page), "the page passes only the brand and whether the key is set");
});
