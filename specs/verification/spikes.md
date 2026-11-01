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

# S5 — Laya on Cloud Run (planned, CP-0025)

* **Goal:** decide whether self-hosted Laya can be the voice decision target ([/architecture/supervisor-routing.md](/architecture/supervisor-routing.md)).
* **Setup:** `laya[serve]` with `laya:multilingual` baked into an image, Cloud Run 2 vCPU / 4 GiB, min instances 1, internal ingress; the seeded tenant's profiles; 200 routing-suite decisions.
* **Measure:** decision latency p50 / p95 from the API service; routing-suite accuracy against `jev` (synthetic data, `PHI_MODE=0`) and `llm`; memory use; cold start.
* **Pass:** p95 ≤ 350 ms and accuracy within 3 points of the best target. Otherwise voice uses `ROUTER_VOICE_TARGET=llm` and the result is recorded here.
* **Local run (2026-11-01, not yet on Cloud Run):** `laya==0.4.20` in `infra/laya/Dockerfile` (CPU torch, checkpoint `english`) on the developer's Windows machine under Docker Desktop. Raw calls with three short option descriptions: p50 1,045 ms, p95 1,096 ms over 20 calls; 6 of 8 clear requests right and both vague ones `none` (the two misses, a deductible and a lost card, came back `none`). Through `supervisor.route()` with the seeded profile summaries (≤ 600 chars each): 1.8–1.9 s per decision, and `none` with Jev-scale confidence 0.32–0.54 on all four requests Stage A left open. Laya's own `confidence` is entropy-based (0.05–0.61 here) and is not comparable with Jev's; its `x_jev_confidence` is, and is now used. **Verdict so far: fails the latency bar on this CPU and adds nothing on these requests with long summaries; voice should use `ROUTER_VOICE_TARGET=llm`.** Still to try: the `typed-decisions` checkpoint, `LAYA_THREADS`, Cloud Run 2 vCPU, a GPU.
* **Strategy comparison (2026-11-01, same machine):** 25 held-out member requests written for the test (22 answerable over Customer Care and Claims, 3 vague), seeded profiles, `bge-small-en-v1.5`: embedding top-1 right on 22 of 22 but a clear win (0.80 / 0.10) on only 6; Laya (profile summaries or use-case titles as options) confident on 0 of 22, p50 1.6–2.0 s; both combined orders decide the same 6 with p50 about 1.9 s. Recorded in [CP-0028](/changes/cp-0028-routing-strategies-and-local-laya.md).
* **Decision (2026-11-01):** local Laya is dropped (too slow on CPU, never confident here); its Dockerfile, container and settings are removed. Hosted Jev was not measured (no key; access is waitlisted). The embedding is the default; a Jev-compatible decision model can be switched on by configuration (CP-0028).
* **Hosted Jev comparison (2026-11-01, developer machine):** `typesafe-ai/jev` through Vercel AI Gateway's TypeSafe-compatible API (`DECISION_MODEL_URL=https://ai-gateway.vercel.sh/typesafe`, `DECISION_MODEL_NAME=typesafe-ai/jev`, threshold 0.55, `PHI_MODE=0`, freshly seeded synthetic tenant), one comparison run (`POST /api/routing/runs {compare: true}`, text timeout 1.5 s) over 41 member and staff cases: 16 generated, 25 manual (22 answerable over Customer Care and Claims, 3 vague; claim-status requests left out because both agents list them). Stage A at the default clear win 0.80 / margin 0.10.

  | | Embedding | Jev |
  |---|---|---|
  | Right first choice (38 answerable) | 32 | 34 |
  | Decided without asking | 14 | 37 |
  | Right when decided | 14 of 14 | 34 of 37 |
  | Vague cases asked about (3) | 3 | 3 |
  | Latency p50 / p95 | 5 / 9 ms | 551 / 671 ms |

  On the 22 manual answerable cases the embedding was right first on 21 but decided only 7; Jev decided all 22 and was right on all 22, and answered `none` or below the threshold on the 3 vague ones. Jev's three wrong decisions are generated claim-status cases labelled Customer Care that it (and the embedding's top choice) sent to Claims: both agents list claim status, so the label is ambiguous rather than the model wrong. One generated case (a deductible question) was below the threshold and fell back. **Verdict:** Jev decides far more requests than the embedding at equal or better accuracy, and fits the text budget (1.5 s) but not the voice budget (350 ms) from this machine; voice would fall back to the embedding on most decisions.

# S6 — WebRTC through TURN on Cloud Run (planned, CP-0027)

* **Goal:** confirm Pipecat's small WebRTC transport works from Cloud Run through a managed TURN relay over TLS 443, and measure the added latency against the WebSocket transport ([/architecture/webrtc-transport.md](/architecture/webrtc-transport.md)).
