// Spec: /api/voice-protocol.md (Browser client requirements)
// Downsamples mic audio to 16 kHz mono PCM16 and posts 20 ms frames (320 samples) plus a level value.
class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.pos = 0;
    this.frame = new Int16Array(320);
    this.idx = 0;
    this.levelAcc = 0;
    this.levelN = 0;
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input) return true;
    // linear-interpolation resample
    while (this.pos < input.length) {
      const i = Math.floor(this.pos);
      const frac = this.pos - i;
      const a = input[i];
      const b = i + 1 < input.length ? input[i + 1] : a;
      const s = Math.max(-1, Math.min(1, a + (b - a) * frac));
      this.frame[this.idx++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      this.levelAcc += s * s;
      this.levelN++;
      if (this.idx === this.frame.length) {
        const out = this.frame.slice(0);
        this.port.postMessage({ pcm: out.buffer, level: Math.sqrt(this.levelAcc / this.levelN) }, [out.buffer]);
        this.idx = 0;
        this.levelAcc = 0;
        this.levelN = 0;
      }
      this.pos += this.ratio;
    }
    this.pos -= input.length;
    return true;
  }
}

registerProcessor("pcm-capture", PcmCapture);
