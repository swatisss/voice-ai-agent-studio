---
type: Spike Report
title: Spikes and verified integration notes
description: Experiments that de-risk the voice loop, LLM tool calling and Cloud Run, plus versions and API names verified against installed packages.
status: stable
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

# S4 — Phone channel and realtime voice (2026-10-16, CP-0012)

* **Goal:** confirm the Pipecat and provider facts [CP-0012](/changes/cp-0012-phone-channel-and-realtime-voice.md) relies on, before writing code.
* **Environment:** Pipecat 1.12.0, Python 3.12, `websockets` 17.2. This session had **no OpenAI or Twilio credentials and no route to either service**, so everything below is read from the installed packages and exercised against a local scripted Realtime server; items that need the real services are listed under "Still to verify".

**Verified against the installed package**

* `pipecat.services.openai.realtime.OpenAIRealtimeLLMService` is driven by Pipecat's `LLMContext` aggregators: a response starts from an `LLMContextFrame`, tool results travel back through the context, `LLMMessagesAppendFrame` is unimplemented ("NEED TO IMPLEMENT" in the source), and there is no way to ask for an exact-text response or to cancel one from outside. That does not fit an `AgentSession`-driven call, so the platform speaks the provider's WebSocket protocol itself (`voiceai/voice/realtime.py`) and uses Pipecat for transports, serializers and frames only. The provider socket sits behind a small interface so the whole bridge runs against a scripted fake in tests.
* Provider protocol (event names read from Pipecat's `events.py` for this release): `session.update` with `session.audio.input.{format, transcription, turn_detection}`, `session.audio.output.{format, voice}`, `output_modalities`, `instructions`, `tools`, `tool_choice`; formats `audio/pcm` (24,000 Hz), `audio/pcmu`, `audio/pcma`; server events `response.created`, `response.output_audio.delta`, `response.output_audio_transcript.delta`, `response.function_call_arguments.done`, `response.done` (usage with `input_token_details.audio_tokens` and `output_token_details.audio_tokens`), `input_audio_buffer.speech_started` / `speech_stopped`, `conversation.item.input_audio_transcription.completed`; client events `input_audio_buffer.append`, `conversation.item.create` (`function_call_output`), `conversation.item.truncate`, `response.create` (with `instructions`, `tool_choice`, `metadata`), `response.cancel`. Connection: `wss://api.openai.com/v1/realtime?model=<model>` with `Authorization: Bearer`.
* Defaults in this Pipecat release: model `gpt-realtime-2.1` (reasoning-capable), input transcription model `gpt-realtime-whisper`; voices named in its OpenAI TTS list include marin, cedar, coral, alloy, ash, ballad, echo, sage, shimmer, verse. These are what `models.yaml` uses.
* `pipecat.serializers.twilio.TwilioFrameSerializer(stream_sid, call_sid, account_sid, auth_token, params)`: mu-law 8 kHz to PCM at the pipeline rate and back, `InterruptionFrame` becomes a `clear` event, DTMF supported. With its default `auto_hang_up=True` it needs credentials and calls the Twilio REST API on `EndFrame`/`CancelFrame`; we turn that off and let `<Hangup/>` and our own transfer do it. It does not turn a Twilio `stop` event into a frame (`PhoneSerializer` does) and it never sees `start`, so the route reads `connected` and `start` itself before building the transport.
* Pipecat's stream resampler returns audio in bursts: with 20 ms Twilio frames the first PCM arrives after 5 frames at 16 kHz and 7 frames at 24 kHz, about 100 to 140 ms of added delay on the caller's side. G.711 pass-through to the realtime service (`audio/pcmu`) would avoid it; left as a later optimisation ([/architecture/telephony.md](/architecture/telephony.md)).

**Exercised offline**

* A scripted Realtime server on localhost and the real Pipecat transport: a signed webhook, the Twilio stream, the welcome as exact text, welcome protection and release, a caller turn, a stored reply with usage and cost, a `stop` event ending the call with `hangup` (`tests/test_telephony.py::test_phone_call_runs_end_to_end_through_the_pipeline`). The same flow was run once as a separate server process with `scripts/fake_twilio.py` against a scripted provider: 1 call, 3 stored events, 3.3 s of agent audio returned, no errors in the API log.

**Still to verify with real services** (each is a manual step in [/build/runbook-phone.md](/build/runbook-phone.md); none blocks the code)

* The Realtime model ID, voices and prices in the OpenAI console, and that `gpt-realtime-2.1` accepts the `session.update` this module sends.
* Measured end-of-speech to first-audio latency (target p50 < 0.8 s, p95 < 1.5 s) over 20 turns, browser and phone, and how many concurrent calls one 2 vCPU Cloud Run instance holds for each pipeline.
* Whether Twilio also signs the stream handshake (the call-bound token is the control the spec relies on), and how the IVR's SIP headers or URL parameters reach the webhook.
* A trial-number call from a real phone, the transfer redirect, and Cloud Run with `PUBLIC_BASE_URL`.

