// Spec: /ui/test-call.md (End of a call and feedback), /ui/calls.md, /ui/insights.md, /architecture/call-ending-and-feedback.md
"use client";

import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Badge, Button, Textarea, useToast } from "./ui";

/** "Helpful" / "Not helpful": always a text label, never only an icon or a color. */
export function FeedbackBadge({ rating }: { rating: string | null | undefined }) {
  if (rating === "up") return <Badge tone="ok"><ThumbsUp size={12} aria-hidden="true" />Helpful</Badge>;
  if (rating === "down") return <Badge tone="warn"><ThumbsDown size={12} aria-hidden="true" />Not helpful</Badge>;
  return null;
}

type Step = "ask" | "comment" | "sent";

/** The caller's thumbs up or down after a call has ended (UI-34). */
export function FeedbackPrompt({ callId }: { callId: string }) {
  const toast = useToast();
  const [step, setStep] = useState<Step>("ask");
  const [sent, setSent] = useState<"up" | "down" | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);

  async function send(rating: "up" | "down", text?: string) {
    setBusy(true);
    try {
      await api(`/api/calls/${callId}/feedback`, { method: "POST", json: { rating, comment: text?.trim() || undefined } });
      setSent(rating);
      setStep("sent");
    } catch (e) {
      toast(e instanceof ApiError ? e.detail : "Could not save your feedback", "bad");
    } finally {
      setBusy(false);
    }
  }

  if (step === "sent") {
    return (
      <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg bg-neutral-soft px-3 py-2 text-sm" role="status">
        <span>Thanks for your feedback.</span>
        <FeedbackBadge rating={sent} />
        <Button variant="ghost" onClick={() => { setStep("ask"); setComment(""); }}>Change answer</Button>
      </div>
    );
  }
  if (step === "comment") {
    return (
      <div className="mt-3 space-y-2 rounded-lg bg-neutral-soft px-3 py-3 text-sm">
        <label className="block font-medium" htmlFor="feedback-comment">What went wrong? (optional)</label>
        <Textarea id="feedback-comment" rows={2} maxLength={300} value={comment} onChange={(e) => setComment(e.target.value)} />
        <div className="flex items-center gap-2">
          <Button variant="primary" loading={busy} onClick={() => send("down", comment)}>Send</Button>
          <Button variant="ghost" onClick={() => setStep("ask")}>Back</Button>
          <span className="ml-auto text-xs text-muted">{comment.length}/300</span>
        </div>
      </div>
    );
  }
  return (
    <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg bg-neutral-soft px-3 py-2 text-sm">
      <span className="font-medium" id="feedback-question">Was this helpful?</span>
      <div className="flex gap-2" role="group" aria-labelledby="feedback-question">
        <Button variant="secondary" loading={busy} aria-label="Yes, this was helpful" onClick={() => send("up")}><ThumbsUp size={14} aria-hidden="true" />Yes</Button>
        <Button variant="secondary" aria-label="No, this was not helpful" onClick={() => setStep("comment")}><ThumbsDown size={14} aria-hidden="true" />No</Button>
      </div>
    </div>
  );
}
