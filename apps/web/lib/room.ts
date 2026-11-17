// Spec: /architecture/hosted-media-room.md (Control messages), /ui/test-call.md (Voice room, LKH-22..LKH-24), /ui/agent-desk.md (LKH-25..LKH-28)
"use client";

/** Control messages the server sends over the room's data channel, topic `echo.control`. */
export type RoomControl =
  | { type: "ready" }
  | { type: "handover"; state: "waiting" | "connected" | "waiting_again"; specialist?: string }
  | { type: "end"; reason: string };

export type RoomHandlers = {
  onConnected?: () => void;
  onControl?: (msg: RoomControl) => void;
  onLevel?: (level: number) => void;
  onSpeaking?: (speaking: boolean) => void;
  onClose?: () => void;
};

export const CONTROL_TOPIC = "echo.control";

/**
 * One browser's connection to a LiveKit room: publishes the microphone, plays whatever the others publish, and
 * reports control messages. The token is used once and never shown or stored. `livekit-client` is loaded on first
 * use so the other pages do not carry it.
 */
export class RoomClient {
  private room: any = null;
  private elements: HTMLMediaElement[] = [];
  private closed = false;

  constructor(private h: RoomHandlers) {}

  async start(url: string, token: string): Promise<void> {
    const { Room, RoomEvent, Track } = await import("livekit-client");
    const room = new Room({ audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    this.room = room;
    room.on(RoomEvent.TrackSubscribed, (track: any) => {
      if (track.kind !== Track.Kind.Audio) return;
      const el = track.attach() as HTMLMediaElement;
      el.autoplay = true;
      document.body.appendChild(el);
      this.elements.push(el);
    });
    room.on(RoomEvent.ActiveSpeakersChanged, (speakers: any[]) => {
      this.h.onSpeaking?.(speakers.some((s) => !s.isLocal));
      this.h.onLevel?.(Math.max(0, ...speakers.filter((s) => s.isLocal).map((s) => s.audioLevel ?? 0)));
    });
    room.on(RoomEvent.DataReceived, (payload: Uint8Array, _p: unknown, _k: unknown, topic?: string) => {
      if (topic !== CONTROL_TOPIC) return;
      try { this.h.onControl?.(JSON.parse(new TextDecoder().decode(payload)) as RoomControl); } catch { /* not ours */ }
    });
    room.on(RoomEvent.Disconnected, () => { this.cleanup(); this.h.onClose?.(); });
    await room.connect(url, token);
    await room.localParticipant.setMicrophoneEnabled(true);  // throws when the microphone is denied
    this.h.onConnected?.();
  }

  /** Mute silences the microphone only (LKH-27). */
  async setMuted(muted: boolean): Promise<void> {
    await this.room?.localParticipant.setMicrophoneEnabled(!muted);
  }

  hangup(): void {
    try { this.room?.disconnect(); } catch { /* already gone */ }
    this.cleanup();
  }

  private cleanup(): void {
    if (this.closed) return;
    this.closed = true;
    try { this.room?.localParticipant.setMicrophoneEnabled(false); } catch { /* disconnected */ }  // release the microphone
    this.elements.forEach((el) => el.remove());
    this.elements = [];
  }
}
