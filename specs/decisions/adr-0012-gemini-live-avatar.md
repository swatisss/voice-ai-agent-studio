---
type: Decision Record
title: ADR-0012 Gemini Live for the avatar engine
description: "Add a second video engine that runs one Gemini Live session on Vertex AI, whose avatar video and voice arrive together and are relayed over our WebSocket, keeping LiveKit with Simli as the fallback."
status: draft
tags: [decision, video, avatar, gemini, live, latency]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-15T00:00:00Z" }
---

# Context

The video path built in [ADR-0009](/decisions/adr-0009-video-channel.md) and [ADR-0011](/decisions/adr-0011-avatar-simli.md) is a chain: speech-to-text, our turn handling, the language model, text-to-speech, Simli, then LiveKit. After the fixes in CP-0016 and CP-0017 it no longer drifts, but it still does not feel live, because latency is the sum of the hops and each hop buffers. A reference implementation ([awesome-llm-apps PR #1203](https://github.com/Shubhamsaboo/awesome-llm-apps/pull/1203)) feels instant and the reason is structural: it has one hop. Its Gemini Live session listens, thinks and speaks, and with `response_modalities: VIDEO` and an `avatar_config` it returns a fragmented MP4 in which the avatar's face and voice are one stream.

What was established, and how reliably:

| Claim | Source | Status |
|---|---|---|
| The session returns avatar video and voice muxed in `video/mp4`; the server forwards chunks over a WebSocket; the browser plays them with MediaSource | The PR's client and server code, read directly | Read from code |
| The avatar path uses the Vertex AI client (`vertexai=True`, project, location, Application Default Credentials); `GOOGLE_API_KEY` is not enough | The PR's code and README | Read from code |
| The model id defaults to `gemini-3.8-live`; tools can be `NON_BLOCKING`; caller speech interrupts the session | The PR's code | Read from code |
| Gemini 3.8 Live with Live Avatar is generally available in Gemini Enterprise, US and EU endpoints; custom avatars need allowlisting | Google's announcement and press | Secondary; the announcement gives no model id, latency or price |
| A stock avatar works on an ordinary Vertex project | Nothing | **Unverified.** The README only states the allowlist requirement for custom portraits |
| Latency is "almost instant" | The requester's viewing of the demo | **Unmeasured** |

# Options

1. **Gemini Live with Google's avatar, relayed over our WebSocket (chosen).** One hop. Fewest moving parts at runtime; depends on Google access we have not verified.
2. **Gemini Live for voice, HeyGen LiveAvatar for the face.** HeyGen publishes a connector for it. Keeps a second vendor, a WebRTC leg and a lip-sync hop, so it gives back some of the latency, but works with ordinary keys.
3. **Gemini Live audio only, keep Simli for the face.** Removes speech-to-text, the model hop and text-to-speech but keeps Simli's re-timing and LiveKit. Faster than today, not instant.
4. **Keep the current chain and tune.** Done as far as it goes in CP-0016 and CP-0017.

# Decision

Option 1, as a **second engine behind a configuration switch**, and **not** a replacement. The LiveKit and Simli engine stays as the fallback and as the only engine for a deployment that cannot use Vertex AI. A spike (CP-0018, T36) settles the unverified rows above before any code is written; if the stock avatar is not available to the project, the fallback inside this decision is option 3's cousin: the same Live engine **audio-only** (GL-05), which keeps most of the latency win and shows the placeholder tile.

Everything that makes the product more than a voice demo stays ours and runs on top of the session: tools through the conversation module's executor, the identity gate, transcripts as call events, the safety screen, escalation and the call-ending rules, and the camera evidence flow ([/architecture/live-session.md](/architecture/live-session.md)).

# Consequences

* **Two engines to keep working.** Their criteria differ (AV-* and VI-* for LiveKit; GL-* and LV-* here). The cost of keeping both is accepted until the Live engine has proved itself, and retiring one is a later proposal.
* **Turn-taking is Google's.** Normal and semantic turn detection and live persona switching are not available on this engine (LV-06). One configured voice and avatar serve every agent.
* **The safety message cannot be guaranteed verbatim.** The model is instructed to speak the fixed text; the screen, the escalation and the recorded wording stay deterministic (GL-08). This is a regression against rule 6 for audio wording and is raised for review.
* **More of the call goes to Google.** The caller's speech streams to Vertex AI for the whole call. The camera does not: stills are pulled on demand, over our socket, and go to the `vision` role as they do now (GL-11). A BAA with Google is a production gap (rule 14).
* **A new third-party SDK in the blast radius.** `google-genai` is imported in one adapter only; `arch_check` enforces it, as it does for Pipecat (GL-13).
* **No WebRTC for this engine.** The path is a WebSocket on the API's own origin, so ADR-0002's Cloud Run concerns do not return. It needs a service account with Vertex AI access.
* **Evaluation does not exercise it.** Simulation and the judge run the text runtime. A change to the Live engine's behaviour is checked by the spike, tests with a fake session, and by hand.
* **Custom avatar faces remain out of scope**, for the reasons in ADR-0011, now with the added fact that Google gates them.
