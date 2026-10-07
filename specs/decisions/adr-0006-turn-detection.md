---
type: Decision Record
title: ADR-0006 Turn detection on Pipecat
description: Implement normal and semantic end-of-turn detection inside the existing Pipecat pipeline instead of adopting LiveKit's turn detector, keeping the model-agnostic, browser-WebSocket design.
status: stable
tags: [decision, voice, turn-detection]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-06T00:00:00Z" }
---

# Context

Callers pause mid-sentence while reading out numbers or thinking. LiveKit Agents offers several turn-detection strategies: VAD only, speech-to-text endpointing, and a small semantic *turn-detector model* that reads the transcript to predict whether the user is done. The team wants those choices selectable and adjustable from the UI, per agent and live during a call.

[ADR-0002](/decisions/adr-0002-voice-pipeline.md) chose Pipecat over a plain WebSocket because it runs unchanged on localhost and Cloud Run (no UDP/WebRTC media server) and is reused for telephony later.

# Options

1. **Move the voice layer to LiveKit** to use its turn-detector model: adds a media server, tokens and dispatch, and a model dependency; reverses ADR-0002.
2. **Pipecat's audio-based Smart Turn model**: ships in the package, but works on audio inside Pipecat's own turn management, which this pipeline bypasses; adds ONNX inference and cannot be exercised without real speech in CI.
3. **Our own turn aggregator with two modes** (silence-only, and silence plus a semantic check): small, deterministic, testable without audio, adjustable at runtime.

# Decision

Option 3. Semantic detection reads the transcript and the agent's last question (is a member ID still being dictated? did the sentence end on "and"?). The check is a local heuristic by default and optionally a fast LLM call, with the heuristic as fallback. Settings live in agent config, can be overridden per call and changed live.

# Consequences

* No new infrastructure; behavior is unit-tested with synthetic transcripts and timers ([/architecture/turn-detection.md](/architecture/turn-detection.md)).
* The heuristic is English-only and rule-based; the LLM evaluator trades about one small model call per turn for better judgment.
* Pipecat's Smart Turn model remains a candidate third evaluator once real-audio evaluation is available.
* If the voice layer ever moves to LiveKit, the same settings map onto its turn-detection options.
