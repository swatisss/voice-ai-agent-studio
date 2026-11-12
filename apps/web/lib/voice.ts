// Spec: /api/voice-protocol.md, /ui/test-call.md (Talk mode, Full flow), /api/public-api.md (Voice connect)
"use client";

import { API_BASE } from "./api";

export type VoiceHandlers = {
  onReady?: () => void;
  onLevel?: (level: number) => void;
  onSpeaking?: (speaking: boolean) => void;
  onEnd?: (reason: string) => void;
  onClose?: (code: number, reason: string) => void;
};

function wsUrl(path: string): string {
  const base = API_BASE || window.location.origin;
  return base.replace(/^http/, "ws") + path;
}

/** Jitter buffer: when nothing is queued (a reply starts, or delivery fell behind), hold this much before playing so a
 * late chunk does not break the voice (/api/voice-protocol.md, Browser client requirements). */
const PREBUFFER_S = 0.2;

export class VoiceClient {
  private ws: WebSocket | null = null;
  private stream: MediaStream | null = null;
  private ctxIn: AudioContext | null = null;
  private ctxOut: AudioContext | null = null;
  private playHead = 0;
  private sources = new Set<AudioBufferSourceNode>();
  private stopped = false;

  constructor(private h: VoiceHandlers) {}

  /** A conversation's voice socket (/api/public-api.md, Voice connect): the URL and single-use token from the create call. */
  async startConnect(url: string, token: string): Promise<void> {
    return this.open(() => new WebSocket(url, ["vai.voice.v1", `vai-token.${token}`]));
  }

  async start(callId: string, tenant: string): Promise<void> {
    return this.open(() => new WebSocket(wsUrl(`/api/voice/${callId}?tenant=${encodeURIComponent(tenant)}`)));
  }

  private async open(connect: () => WebSocket): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    this.ctxOut = new AudioContext({ sampleRate: 24000 });
    this.ctxIn = new AudioContext();
    await this.ctxIn.audioWorklet.addModule("/pcm-capture-worklet.js");
    const source = this.ctxIn.createMediaStreamSource(this.stream);
    const node = new AudioWorkletNode(this.ctxIn, "pcm-capture");
    const mute = this.ctxIn.createGain();
    mute.gain.value = 0;
    source.connect(node).connect(mute).connect(this.ctxIn.destination);

    this.ws = connect();
    this.ws.binaryType = "arraybuffer";
    node.port.onmessage = (e: MessageEvent<{ pcm: ArrayBuffer; level: number }>) => {
      this.h.onLevel?.(e.data.level);
      if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(e.data.pcm);
    };
    this.ws.onmessage = (e) => {
      if (typeof e.data === "string") {
        const msg = JSON.parse(e.data);
        if (msg.type === "ready") this.h.onReady?.();
        else if (msg.type === "interrupt") this.flush();
        else if (msg.type === "end") { this.h.onEnd?.(msg.reason); this.cleanup(); }  // the server ended the call: release the microphone now (UI-35)
      } else {
        this.play(e.data as ArrayBuffer);
      }
    };
    this.ws.onclose = (e) => { this.h.onClose?.(e.code, e.reason); this.cleanup(); };
  }

  private play(buf: ArrayBuffer) {
    if (!this.ctxOut || this.stopped) return;
    const pcm = new Int16Array(buf);
    if (!pcm.length) return;
    const audio = this.ctxOut.createBuffer(1, pcm.length, 24000);
    const ch = audio.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 0x8000;
    const src = this.ctxOut.createBufferSource();
    src.buffer = audio;
    src.connect(this.ctxOut.destination);
    const now = this.ctxOut.currentTime;
    const at = this.playHead > now ? this.playHead : now + PREBUFFER_S;  // back-to-back while queued, else rebuffer
    src.start(at);
    this.playHead = at + audio.duration;
    this.sources.add(src);
    this.h.onSpeaking?.(true);
    src.onended = () => {
      this.sources.delete(src);
      if (!this.sources.size) this.h.onSpeaking?.(false);
    };
  }

  /** Barge-in: discard queued agent audio immediately. */
  flush() {
    for (const s of this.sources) { try { s.stop(); } catch { /* already stopped */ } }
    this.sources.clear();
    this.playHead = 0;
    this.h.onSpeaking?.(false);
  }

  hangup() {
    try { this.ws?.send(JSON.stringify({ type: "hangup" })); } catch { /* socket closed */ }
    setTimeout(() => this.ws?.close(), 300);
    this.flush();  // a hang-up cuts the agent off at once
    this.cleanup();
  }

  private cleanup() {
    if (this.stopped) return;
    this.stopped = true;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctxIn?.close().catch(() => undefined);
    // the server finishes sending a goodbye faster than it plays: let what is queued play out before closing
    const queued = this.ctxOut ? Math.max(0, this.playHead - this.ctxOut.currentTime) : 0;
    setTimeout(() => this.ctxOut?.close().catch(() => undefined), 1500 + queued * 1000);
  }
}
