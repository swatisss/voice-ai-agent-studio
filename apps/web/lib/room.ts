// Spec: /api/media-protocol.md, /ui/visual-case.md
"use client";

import {
  ConnectionState,
  LocalVideoTrack,
  RemoteAudioTrack,
  Room,
  RoomEvent,
  Track,
  type RemoteTrack,
  type RemoteTrackPublication,
} from "livekit-client";

export type RoomGrant = { url: string; room: string; token: string; identity: string };

export type RoomHandlers = {
  onReady?: () => void;
  onSpeaking?: (speaking: boolean) => void;
  onCamera?: (on: boolean) => void;
  onEnd?: (reason: string) => void;
  onError?: (message: string) => void;
};

/**
 * One video call: microphone up, agent audio down, and a camera the caller controls.
 *
 * The camera is never enabled on connect — only `setCamera(true)` does it, which is the browser
 * half of the contract that the agent cannot turn it on (VI-02).
 */
export class RoomClient {
  private room: Room | null = null;
  private audio: HTMLAudioElement | null = null;
  private stopped = false;

  constructor(private h: RoomHandlers) {}

  async start(grant: RoomGrant): Promise<void> {
    const room = new Room({ adaptiveStream: true, dynacast: true });
    this.room = room;

    room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack, _pub: RemoteTrackPublication) => {
      if (track.kind === Track.Kind.Audio) {
        this.audio = (track as RemoteAudioTrack).attach();
        this.audio.autoplay = true;
        document.body.appendChild(this.audio);
      }
    });
    room.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
      this.h.onSpeaking?.(speakers.some((p) => p.identity !== room.localParticipant.identity));
    });
    room.on(RoomEvent.Disconnected, () => {
      if (!this.stopped) this.h.onEnd?.("disconnected");
    });
    room.on(RoomEvent.ConnectionStateChanged, (state) => {
      if (state === ConnectionState.Connected) this.h.onReady?.();
    });

    await room.connect(grant.url, grant.token);
    await room.localParticipant.setMicrophoneEnabled(true);
    // The camera stays off. Nothing here turns it on.
  }

  /** Publish or unpublish the camera track. The only way a frame ever reaches the agent. */
  async setCamera(on: boolean): Promise<boolean> {
    const room = this.room;
    if (!room) return false;
    try {
      await room.localParticipant.setCameraEnabled(on, { resolution: { width: 1280, height: 720 } });
      this.h.onCamera?.(on);
      return on;
    } catch (e) {
      this.h.onError?.((e as Error).message || "The camera could not be started.");
      this.h.onCamera?.(false);
      return false;
    }
  }

  /** The local camera track, for a preview the caller can see. Never uploaded beyond the room. */
  cameraTrack(): LocalVideoTrack | null {
    const pub = this.room?.localParticipant.getTrackPublication(Track.Source.Camera);
    return (pub?.videoTrack as LocalVideoTrack | undefined) ?? null;
  }

  hangup(): void {
    this.stopped = true;
    try {
      this.audio?.remove();
      void this.room?.disconnect();
    } catch {
      /* already gone */
    }
    this.room = null;
    this.audio = null;
  }
}
