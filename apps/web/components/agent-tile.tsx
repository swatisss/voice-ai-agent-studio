// Spec: /ui/visual-case.md (The call layout), /architecture/avatar.md
"use client";

import { Bot } from "lucide-react";
import type { LocalVideoTrack, RemoteVideoTrack } from "livekit-client";
import { useEffect, useRef, useState } from "react";
import { Badge, cx } from "@/components/ui";

/** How long an expected avatar gets to arrive before the tile calls it unavailable. */
const AVATAR_WAIT_MS = 10_000;

type Props = {
  name: string;
  agentTrack: RemoteVideoTrack | null;   // the agent's face, when the call has an avatar
  selfTrack: LocalVideoTrack | null;     // the caller's own camera, when it is on
  avatar: boolean;                       // media.avatar: was a face promised for this call?
  connected: boolean;
  speaking: boolean;
};

/**
 * The agent's side of a video call, with the caller's own camera as a small self-view.
 *
 * Always labelled with the persona's name and "AI agent", so the face is never mistaken for a
 * person (UI-46, compliance rule 13). With no face it is a placeholder that says why and still
 * shows when the agent is speaking (UI-47, UI-48), so a missing avatar never looks like a broken
 * call.
 */
export function AgentTile({ name, agentTrack, selfTrack, avatar, connected, speaking }: Props) {
  const agentRef = useRef<HTMLVideoElement>(null);
  const selfRef = useRef<HTMLVideoElement>(null);
  const [waited, setWaited] = useState(false);
  const [hadTrack, setHadTrack] = useState(false);

  // The <video> elements only exist once their track does, so attach after render, never before.
  useEffect(() => {
    const el = agentRef.current;
    if (!el || !agentTrack) return;
    agentTrack.attach(el);
    setHadTrack(true);
    return () => { agentTrack.detach(el); };
  }, [agentTrack]);

  useEffect(() => {
    const el = selfRef.current;
    if (!el || !selfTrack) return;
    selfTrack.attach(el);
    return () => { selfTrack.detach(el); };
  }, [selfTrack]);

  useEffect(() => {  // an expected avatar gets a moment to connect before we call it unavailable
    setWaited(false);
    if (!avatar || !connected || agentTrack || hadTrack) return;
    const t = setTimeout(() => setWaited(true), AVATAR_WAIT_MS);
    return () => clearTimeout(t);
  }, [avatar, connected, agentTrack, hadTrack]);

  const note = agentTrack ? null
    : !avatar ? "No avatar is configured"
    : hadTrack || waited ? "Avatar unavailable — the agent can still be heard"
    : "Connecting the avatar…";

  return (
    <div className="relative mb-3 h-56 w-full overflow-hidden rounded-xl bg-slate-900 text-white" aria-label={`${name}, AI agent`}>
      {agentTrack ? (
        <video ref={agentRef} autoPlay playsInline className="h-full w-full bg-black object-contain" />
      ) : (
        <div className="flex h-full flex-col items-center justify-center gap-2">
          <div className={cx("flex h-20 w-20 items-center justify-center rounded-full bg-accent text-on-accent", speaking && "speaking")}>
            <Bot size={34} />
          </div>
          <div className="text-xs text-white/70">{note}</div>
        </div>
      )}
      <div className="absolute bottom-3 left-3 flex items-center gap-2 rounded-full bg-black/55 px-3 py-1 text-sm">
        <span className="font-medium">{name}</span>
        <Badge tone="accent">AI agent</Badge>
      </div>
      {selfTrack && (
        <div className="absolute bottom-3 right-3 h-20 w-28 overflow-hidden rounded-lg border border-white/40 bg-black shadow-lg">
          <video ref={selfRef} autoPlay playsInline muted className="h-full w-full -scale-x-100 object-cover" aria-label="Your camera" />
        </div>
      )}
    </div>
  );
}
