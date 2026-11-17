// Spec: /ui/agent-console.md
"use client";

import { Bell, BellOff, ChevronDown, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DeskPhone } from "@/components/desk-phone";
import { PacketCard } from "@/components/packet";
import { useTenant } from "@/components/shell";
import { Transcript } from "@/components/transcript";
import { composerNote, DeliveryMark, WhatsappStatus } from "@/components/whatsapp-panel";
import { Badge, Button, Card, cx, EmptyState, Field, Input, Select, Spinner, Tabs, Textarea, useToast } from "@/components/ui";
import { api, ApiError, type Escalation, useApi, useEvents } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { ago, DISPOSITIONS, label, maskRef, REASON } from "@/lib/format";

type Queue = "waiting" | "mine" | "resolved";

export default function ConsolePage() {
  const { tenant } = useTenant();
  const toast = useToast();
  const { data, reload, setData } = useApi<{ items: Escalation[] }>("/api/escalations", [tenant]);
  const [queue, setQueue] = useState<Queue>("waiting");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const session = useMe();
  const signedIn = session.enabled ? session.user?.name : undefined;  // signed in: the assignee is the session's name
  const [typed, setMe] = useState("Specialist");
  const me = signedIn ?? typed;
  const [disposition, setDisposition] = useState("resolved_by_human");
  const [note, setNote] = useState("");
  const [noteErr, setNoteErr] = useState<string | null>(null);
  const [showTranscript, setShowTranscript] = useState(true);
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  const [chime, setChime] = useState(true);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [, tick] = useState(0);
  const audio = useRef<AudioContext | null>(null);

  useEffect(() => { if (!signedIn) try { setMe(localStorage.getItem("specialist") || "Specialist"); } catch { /* ignore */ } }, []);
  useEffect(() => { const t = setInterval(() => tick((x) => x + 1), 1000); return () => clearInterval(t); }, []);

  const loadDetail = useCallback(async (id: string) => {
    const d = await api(`/api/escalations/${id}`);
    setDetail(d);
    setShowTranscript(d.packet_status === "pending");
  }, []);
  useEffect(() => { if (selected) loadDetail(selected); else setDetail(null); }, [selected, loadDetail]);

  function beep() {
    if (!chime) return;
    try {
      audio.current ??= new AudioContext();
      const o = audio.current.createOscillator();
      const g = audio.current.createGain();
      o.frequency.value = 880; g.gain.value = 0.05;
      o.connect(g).connect(audio.current.destination);
      o.start(); o.stop(audio.current.currentTime + 0.15);
    } catch { /* audio blocked */ }
  }

  useEvents(["console"], (e) => {  // UI-12
    if (e.type === "escalation.message") {  // UI-86: a line in the conversation panel
      if (selected === (e.data as { escalation_id: string }).escalation_id) loadDetail(selected);
      return;
    }
    const esc = e.data as Escalation;
    setData((prev) => {
      const items = prev?.items ?? [];
      const idx = items.findIndex((x) => x.id === esc.id);
      const merged = idx >= 0 ? items.map((x) => (x.id === esc.id ? { ...x, ...esc } : x)) : [{ ...esc, call: undefined }, ...items];
      return { items: merged };
    });
    if (e.type === "escalation.created") {
      beep();
      setFresh((s) => new Set(s).add(esc.id));
      setTimeout(() => setFresh((s) => { const n = new Set(s); n.delete(esc.id); return n; }), 3000);
    }
    if (selected === esc.id) loadDetail(esc.id);
  }, tenant);

  const items = useMemo(() => {
    const all = data?.items ?? [];
    const today = new Date().toDateString();
    const list = queue === "waiting" ? all.filter((e) => e.status === "waiting")
      : queue === "mine" ? all.filter((e) => e.status === "accepted" && e.assignee === me)
      : all.filter((e) => e.status === "resolved" && e.resolved_at && new Date(e.resolved_at).toDateString() === today);
    return [...list].sort((a, b) => (a.reason_category === "safety" ? -1 : 0) - (b.reason_category === "safety" ? -1 : 0) || b.created_at.localeCompare(a.created_at));  // UI-14
  }, [data, queue, me]);
  const counts = { waiting: data?.items.filter((e) => e.status === "waiting").length ?? 0 };

  async function accept() {
    try { localStorage.setItem("specialist", me); } catch { /* ignore */ }
    try {
      await api(`/api/escalations/${selected}/accept`, { method: "POST", json: { assignee: me } });
      await loadDetail(selected!);
      reload();
    } catch (e) { toast((e as ApiError).detail, "bad"); }
  }

  async function sendReply() {  // UI-86
    const text = reply.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      await api(`/api/escalations/${selected}/messages`, { method: "POST", json: { text } });
      setReply("");
      await loadDetail(selected!);
    } catch (e) { toast((e as ApiError).detail, "bad"); }
    setSending(false);
  }

  async function resolve() {
    if (note.trim().length < 10) { setNoteErr("Write at least 10 characters — this note teaches the agent."); return; }  // UI-13
    try {
      await api(`/api/escalations/${selected}/resolve`, { method: "POST", json: { disposition, resolution_note: note } });
      toast(session.user?.role === "specialist" ? "Resolved. Thanks, this is now evidence for the learning loop." : "Escalation resolved", "ok");
      setNote(""); setNoteErr(null);
      await loadDetail(selected!);
      reload();
    } catch (e) { toast((e as ApiError).detail, "bad"); }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">Agent console</h1>
        <div className="ml-auto flex items-center gap-2">
          {signedIn ? <span className="text-sm text-muted">Signed in as {signedIn}</span> : <Input className="w-44" value={me} onChange={(e) => setMe(e.target.value)} aria-label="Your name" />}
          <Button variant="ghost" onClick={() => setChime(!chime)} aria-label="Toggle chime">{chime ? <Bell size={16} /> : <BellOff size={16} />}</Button>
        </div>
      </div>
      {session.user?.role !== "reviewer" && <DeskPhone items={data?.items ?? []} onSelect={setSelected} onChanged={reload} />}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-2">
          <Tabs<Queue> value={queue} onChange={setQueue} tabs={[{ id: "waiting", label: `Waiting (${counts.waiting})` }, { id: "mine", label: "Mine" }, { id: "resolved", label: "Resolved today" }]} />
          {!data ? <Spinner /> : !items.length ? <div className="p-4 text-sm text-muted">Nothing here. New escalations appear automatically.</div> : (
            <ul className="space-y-2">
              {items.map((e) => (
                <li key={e.id}>
                  <button onClick={() => setSelected(e.id)}
                    className={cx("w-full rounded-xl border bg-panel p-3 text-left", selected === e.id ? "border-accent" : "border-line", fresh.has(e.id) && "flash")}>
                    <div className="flex items-center gap-2">
                      <Badge tone={e.reason_category === "safety" ? "bad" : "warn"}>{REASON[e.reason_category] ?? label(e.reason_category)}</Badge>
                      <span className="ml-auto text-xs text-muted">{ago(e.created_at)}</span>
                    </div>
                    <div className="mt-1 text-sm">{e.packet ? label(e.packet.intent) : e.reason_detail || "Preparing notes…"}</div>
                    <div className="mt-0.5 text-xs text-muted">Caller {maskRef(e.call?.caller_ref ?? (e.packet?.entities?.member_ref as string))} {e.packet && `· ${e.packet.sentiment.end}`}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="space-y-4 lg:col-span-2">
          {!detail ? <EmptyState title="Select an escalation">The groundwork packet appears here — read it before you greet the caller.</EmptyState> : (
            <>
              <PacketCard esc={detail} />
              <Card title={<button className="flex items-center gap-1" onClick={() => setShowTranscript(!showTranscript)}>{showTranscript ? <ChevronDown size={14} /> : <ChevronRight size={14} />}Transcript</button>}>
                {showTranscript ? <Transcript events={detail.events} /> : <div className="text-sm text-muted">{detail.events.filter((x: any) => x.kind === "user").length} caller turns</div>}
              </Card>
              {detail.human_thread && (
                <Card title="Conversation" actions={<Badge tone={detail.conversation_status === "ended" ? "neutral" : "ok"}>{detail.conversation_status === "ended" ? "Ended" : "Live chat"}</Badge>}>
                  {detail.channel_state && <WhatsappStatus state={detail.channel_state} />}
                  <ul className="max-h-80 space-y-2 overflow-y-auto" aria-live="polite" data-testid="conversation-thread">
                    {detail.events.filter((x: any) => ["user", "assistant", "human"].includes(x.kind) && x.text).map((x: any) => (
                      <li key={x.seq} className={cx("flex", x.kind === "human" ? "justify-end" : "justify-start")}>
                        <div className={cx("max-w-[80%] rounded-xl px-3 py-2 text-sm", x.kind === "human" ? "bg-accent text-white" : x.kind === "user" ? "bg-neutral-soft" : "border border-line bg-panel")}>
                          <div className="text-[11px] opacity-70">{x.kind === "human" ? (x.data?.author ?? "You") : x.kind === "user" ? "Customer" : "Virtual assistant"}</div>
                          {x.text}
                          {x.kind === "human" && detail.channel_state && <DeliveryMark delivery={x.data?.delivery} />}
                        </div>
                      </li>
                    ))}
                  </ul>
                  <form className="mt-3 flex gap-2" onSubmit={(ev) => { ev.preventDefault(); sendReply(); }}>
                    <Input className="flex-1" value={reply} maxLength={2000} onChange={(ev) => setReply(ev.target.value)} aria-label="Reply to the customer"
                      disabled={detail.status !== "accepted" || detail.conversation_status === "ended" || !!composerNote(detail.channel_state)}
                      placeholder={composerNote(detail.channel_state) ?? (detail.status === "waiting" ? "Accept to reply" : detail.status === "accepted" && detail.conversation_status !== "ended" ? "Type a reply" : "This conversation is closed")} />
                    <Button variant="primary" type="submit" disabled={detail.status !== "accepted" || detail.conversation_status === "ended" || !!composerNote(detail.channel_state) || !reply.trim() || sending}>Send</Button>
                  </form>
                </Card>
              )}
              <Card title="Handle" actions={<Badge tone={detail.status === "resolved" ? "ok" : "warn"}>{label(detail.status)}</Badge>}>
                {detail.status === "waiting" && <Button variant="primary" onClick={accept}>Accept</Button>}
                {detail.status === "accepted" && (
                  <div className="space-y-3">
                    <div className="text-sm text-muted">Accepted by {detail.assignee}</div>
                    <Field label="Disposition"><Select value={disposition} onChange={(e) => setDisposition(e.target.value)}>{DISPOSITIONS.map((d) => <option key={d} value={d}>{label(d)}</option>)}</Select></Field>
                    <Field label="Resolution note" hint="What did you tell the caller? This teaches the agent." error={noteErr}>
                      <Textarea value={note} onChange={(e) => { setNote(e.target.value); setNoteErr(null); }} />
                    </Field>
                    <Button variant="primary" onClick={resolve}>Resolve</Button>
                  </div>
                )}
                {detail.status === "resolved" && (
                  <div className="space-y-1 text-sm"><div>{label(detail.disposition)} · {detail.assignee}</div><div className="rounded-lg bg-neutral-soft p-2">{detail.resolution_note}</div></div>
                )}
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
