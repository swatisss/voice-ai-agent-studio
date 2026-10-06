---
type: Spike Report
title: Spikes and verified integration notes
description: Experiments that de-risk the voice loop, LLM tool calling and Cloud Run, plus versions and API names verified against installed packages.
status: draft
tags: [verification, spikes]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

Fill in each spike's **Result** with measured numbers and dates. Findings that change behavior go through a CP.

# S1 — Browser voice loop

* **Goal:** browser mic → WS → Pipecat (Silero VAD, Deepgram STT/TTS) → Groq → speaker works on localhost with barge-in.
* **Measure:** p50/p95 end-of-speech → first audio over 20 turns; false interruptions with laptop speakers vs headset; Deepgram endpointing vs our 350 ms turn delay.
* **Result:** _pending (needs `DEEPGRAM_API_KEY` and `GROQ_API_KEY`)._

# S2 — Groq tool-calling reliability

* **Goal:** `openai/gpt-oss-120b` vs `openai/gpt-oss-20b` at `reasoning_effort: low` follow the system prompt: verify before PHI, call `search_knowledge` before policy answers, escalate appeals, short spoken replies.
* **Method:** run the six regression scenarios × 5 with the evaluator (`uv run voiceai eval-scenarios`).
* **Result:** _pending._

# S3 — Cloud Run

* **Goal:** WebSocket voice and SSE survive on Cloud Run with session affinity; cold start with baked fastembed model.
* **Result:** _pending._

# Verified versions and APIs

Recorded during the CP-0001 build on 2026-10-06 (exact pins in `apps/api/uv.lock`, `apps/web/package-lock.json`):

| Package | Version | Notes |
|---|---|---|
| pipecat-ai | 1.12.0 | see API notes below |
| openai (Python) | 3.24.0 | `AsyncOpenAI`, `chat.completions.create(..., reasoning_effort=, stream_options=)` and the exception classes used by the gateway are unchanged from 1.x |
| fastapi / sqlalchemy | 0.142.2 / 2.1.3 | |
| fastembed | 0.8.1 | `TextEmbedding.passage_embed` / `query_embed` |
| Python / Node | 3.12.10 / 24.19.0 | |

Pipecat 1.12 API facts the voice code depends on (verified against the installed package; guarded by `tests/test_voice_smoke.py`):

* VAD is **not** a transport param any more: use `pipecat.processors.audio.vad_processor.VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=...)))`; it emits `VADUserStartedSpeakingFrame` / `VADUserStoppedSpeakingFrame`.
* Barge-in: a processor calls `await self.broadcast_interruption()`, which sends `InterruptionFrame` both ways; the websocket output transport passes it to the serializer (we emit `{"type":"interrupt"}`).
* `FrameSerializer` subclasses implement `async serialize(frame) -> str|bytes|None` and `async deserialize(data) -> Frame|None`; `EndFrame`/`CancelFrame` reach `serialize` on stop (we emit `{"type":"end"}`).
* `FastAPIWebsocketParams(audio_in_enabled, audio_in_sample_rate, audio_out_enabled, audio_out_sample_rate, serializer, session_timeout, add_wav_header)`; JSON text from the client arrives as a broadcast `InputTransportMessageFrame(message=...)`.
* `DeepgramSTTService(api_key, sample_rate, settings=DeepgramSTTService.Settings(model, language, smart_format, punctuate, interim_results))`; `DeepgramTTSService(api_key, voice, sample_rate)`.
* TTS services aggregate `LLMTextFrame`s between `LLMFullResponseStartFrame` and `LLMFullResponseEndFrame` into sentences.
* `PipelineTask(pipeline, params=PipelineParams(audio_in_sample_rate, audio_out_sample_rate))`, `PipelineRunner(handle_sigint=False).run(task)`; `task.queue_frame(EndFrame())` ends gracefully.

Still unverified (needs live keys, see S1): VO-01 greeting audio and VO-03 barge-in behavior end to end.

# Embedding thresholds (measured 2026-10-06, `BAAI/bge-small-en-v1.5`)

| Check | Score | Verdict |
|---|---|---|
| "how do I replace my lost insurance card" → Member ID cards | 0.736 | answer (≥ 0.60) |
| "what is my copay for urgent care on silver" → Copays by plan | 0.785 | answer |
| "how do I add my newborn baby to my plan" | < 0.60 | **no answer** — the planted gap works |
| "quantum physics lecture" | < 0.60 | no answer |
| New newborn phrasings vs newborn centroid | 0.883–0.887 | joins cluster (≥ 0.80) |
| Prior-auth phrasing vs prior-auth centroid | 0.945 | joins cluster |
| Cross-topic similarities | 0.53–0.63 | separate clusters |

Seeding with fastembed takes ~45 s on a laptop CPU (first run also downloads ~70 MB).
