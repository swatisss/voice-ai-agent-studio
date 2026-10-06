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

Recorded during the CP-0001 build (see `apps/api/uv.lock`, `apps/web/package-lock.json` for exact pins):

* _to be filled by T17 (Pipecat class and frame names actually used)._
