// Spec: /ui/chat-app.md, /architecture/external-chat-app.md
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type Item = { id: string; speaker: "caller" | "front_desk" | "agent" | "human"; text: string; at: string; author?: string };
type Escalation = { id: string; status: "waiting" | "accepted" | "resolved"; assignee: string | null } | null;
type View = { conversation_id: string; status: "active" | "escalated" | "ended"; escalation: Escalation; items: Item[]; cursor: string | null };
type Notice = { key: string; kind: "wait" | "human" | "end"; text: string; after: string | null };

const STORE = "chat.conversation";
const FRIENDLY = "We can't reach the assistant. Try again.";

class Failure extends Error {
  constructor(public status: number, public code: string, message: string, public retryAfter?: number) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers: { "Content-Type": "application/json" }, cache: "no-store" });
  } catch {
    throw new Failure(0, "network", FRIENDLY);
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Failure(res.status, body.error ?? "error", body.detail ?? FRIENDLY, Number(res.headers.get("retry-after")) || undefined);
  return body as T;
}

const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

export function Chat({ brand, configured }: { brand: string; configured: boolean }) {
  const [convId, setConvId] = useState<string | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [status, setStatus] = useState<View["status"]>("active");
  const [escalation, setEscalation] = useState<Escalation>(null);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [gone, setGone] = useState(false);
  const cursor = useRef<string | null>(null);
  const seen = useRef<Set<string>>(new Set());
  const last = useRef<string | null>(null);
  const noticed = useRef<Set<string>>(new Set());
  const bottom = useRef<HTMLDivElement | null>(null);

  const addNotice = useCallback((n: Omit<Notice, "after">) => {
    if (noticed.current.has(n.key)) return;
    noticed.current.add(n.key);
    setNotices((all) => [...all, { ...n, after: last.current }]);
  }, []);

  const apply = useCallback((v: View) => {
    const fresh = v.items.filter((i) => !seen.current.has(i.id));
    fresh.forEach((i) => seen.current.add(i.id));
    if (fresh.length) {
      last.current = fresh[fresh.length - 1].id;
      setItems((all) => [...all, ...fresh]);
    }
    if (v.cursor) cursor.current = v.cursor;
    setStatus(v.status);
    setEscalation(v.escalation);
    if (v.escalation) addNotice({ key: "wait", kind: "wait", text: "We're connecting you to a specialist. This usually takes a few minutes." });
    if (v.escalation && v.escalation.status !== "waiting")
      addNotice({ key: "human", kind: "human", text: `You're now talking to a human agent.${v.escalation?.assignee ? ` ${v.escalation.assignee} has joined the chat.` : ""}` });
    if (v.status === "ended") addNotice({ key: "end", kind: "end", text: "This chat has ended. Thanks for contacting us." });
    setError(null);
  }, [addNotice]);

  const reset = useCallback(() => {
    try { sessionStorage.removeItem(STORE); } catch { /* storage blocked */ }
    cursor.current = null; seen.current = new Set(); last.current = null; noticed.current = new Set();
    setItems([]); setNotices([]); setEscalation(null); setStatus("active"); setConvId(null); setGone(false);
  }, []);

  const begin = useCallback(async () => {
    reset();
    try {
      const v = await request<View>("/api/chat", { method: "POST", body: JSON.stringify({}) });
      setConvId(v.conversation_id);
      try { sessionStorage.setItem(STORE, v.conversation_id); } catch { /* storage blocked */ }
      apply(v);
    } catch (e) { setError((e as Failure).message); }
  }, [apply, reset]);

  // On load: resume the stored conversation (CHAT-05), else start one.
  useEffect(() => {
    if (!configured) return;
    let stored: string | null = null;
    try { stored = sessionStorage.getItem(STORE); } catch { /* storage blocked */ }
    if (!stored) { begin(); return; }
    setConvId(stored);
    request<View>(`/api/chat/${stored}/messages`)
      .then(apply)
      .catch((e: Failure) => { if (e.status === 404) { reset(); setGone(true); } else setError(e.message); });
  }, [configured, begin, apply, reset]);

  // Polling: 2 s while a specialist is involved, 5 s otherwise, stopped when ended, paused when the tab is hidden (CHAT-04).
  useEffect(() => {
    if (!convId || status === "ended") return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      let wait = status === "escalated" ? 2000 : 5000;
      if (!document.hidden && !sending) {
        try {
          apply(await request<View>(`/api/chat/${convId}/messages${cursor.current ? `?cursor=${encodeURIComponent(cursor.current)}` : ""}`));
        } catch (e) {
          const f = e as Failure;
          if (f.status === 404) { reset(); setGone(true); return; }
          if (f.status === 429) wait = (f.retryAfter ?? 3) * 1000;  // CHAT-06: wait quietly, no visible error
          else setError(f.message);
        }
      }
      if (!stop) timer = setTimeout(tick, wait);
    };
    timer = setTimeout(tick, status === "escalated" ? 2000 : 5000);
    return () => { stop = true; clearTimeout(timer); };
  }, [convId, status, sending, apply, reset]);

  useEffect(() => { bottom.current?.scrollIntoView({ block: "end" }); }, [items, notices, sending]);

  async function send() {
    const line = text.trim();
    if (!line || sending || !convId || status === "ended") return;
    setSending(true); setText(""); setError(null);
    const temp: Item = { id: `tmp-${Date.now()}`, speaker: "caller", text: line, at: new Date().toISOString() };
    setItems((all) => [...all, temp]);
    try {
      const v = await request<View>(`/api/chat/${convId}/messages`, { method: "POST", body: JSON.stringify({ text: line, cursor: cursor.current }) });
      setItems((all) => all.filter((i) => i.id !== temp.id));
      apply(v);
    } catch (e) {
      const f = e as Failure;
      setItems((all) => all.filter((i) => i.id !== temp.id));
      setText(line);  // CHAT-06: the typed text stays in the box
      if (f.status === 404) { reset(); setGone(true); } else setError(f.message);
    }
    setSending(false);
  }

  async function endChat() {
    if (!convId) return;
    try { await request(`/api/chat/${convId}/end`, { method: "POST" }); apply(await request<View>(`/api/chat/${convId}/messages${cursor.current ? `?cursor=${encodeURIComponent(cursor.current)}` : ""}`)); }
    catch (e) { setError((e as Failure).message); }
  }

  if (!configured) {
    return (
      <div className="shell"><main className="chat"><div className="setup">
        <h1>{brand} chat is not set up</h1>
        <p>This server has no API key yet. Set <code>VOICEAI_API_KEY</code> (a member key from Studio, Settings, API keys) in <code>apps/chat/.env.local</code>, then restart the app.</p>
        <p>The platform address is read from <code>VOICEAI_API_URL</code>.</p>
      </div></main></div>
    );
  }

  const ended = status === "ended" || gone;
  const accepted = escalation && escalation.status !== "waiting" && !ended;
  const headline = ended ? "Chat ended"
    : accepted ? `Talking with ${escalation?.assignee ?? "a specialist"}, specialist`
    : status === "escalated" ? "Connecting you to a specialist…" : "Virtual assistant";
  const noticesAfter = (id: string | null) => notices.filter((n) => n.after === id);

  return (
    <div className="shell">
      <main className="chat" aria-label={`${brand} member support chat`}>
        <header className="head">
          <div className="avatar" aria-hidden>{brand.slice(0, 1)}</div>
          <div><h1>{brand} · Member support</h1><div className="sub" data-testid="status">{headline}</div></div>
          <button onClick={endChat} disabled={ended || !convId}>End chat</button>
        </header>
        <div className={`disclaimer${accepted ? " human" : ""}`} data-testid="disclaimer">
          {accepted ? "You're now chatting with a person from our team."
            : "You're chatting with a virtual assistant. It can make mistakes, so please don't share card numbers or passwords. In an emergency call 999."}
        </div>
        <ol className="thread" aria-live="polite" data-testid="thread">
          {noticesAfter(null).map((n) => <li key={n.key} className={`notice ${n.kind === "human" ? "human" : ""}`}>{n.text}</li>)}
          {items.map((i) => (
            <li key={i.id} style={{ display: "contents" }}>
              <div className={`row ${i.speaker === "caller" ? "caller" : "other"} ${i.speaker === "human" ? "human" : i.speaker === "caller" ? "" : "ai"}`}>
                {i.speaker !== "caller" && <span className="who">{i.speaker === "human" ? `${i.author ?? "Specialist"} · Specialist` : "Virtual assistant"}</span>}
                <div className="bubble">{i.text}</div>
                <span className="time">{clock(i.at)}</span>
              </div>
              {noticesAfter(i.id).map((n) => <div key={n.key} className={`notice ${n.kind === "human" ? "human" : ""}`}>{n.text}</div>)}
            </li>
          ))}
          {sending && status !== "escalated" && <li className="typing" aria-label="The assistant is typing"><i /><i /><i /></li>}
          <div ref={bottom} />
        </ol>
        {error && <div className="error" role="alert">{error}<button onClick={() => { setError(null); if (!convId) begin(); }}>Retry</button></div>}
        {ended ? (
          <div className="ended">{gone && <p>This chat is no longer available.</p>}<button onClick={begin}>Start a new chat</button></div>
        ) : (
          <form className="composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
            <textarea rows={1} value={text} maxLength={2000} aria-label="Your message" disabled={!convId}
              placeholder={status === "escalated" && !accepted ? "Add anything the specialist should know" : "Type your message"}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
            <button type="submit" disabled={sending || !text.trim() || !convId}>Send</button>
          </form>
        )}
      </main>
    </div>
  );
}
