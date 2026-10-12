---
type: Component Spec
title: Visual evidence intake
description: "How a caller's camera becomes grounded evidence: frames captured on demand, a described observation with a confidence it is allowed to withhold, pinned evidence, a case and a routing decision."
status: draft
tags: [architecture, video, vision, evidence, cases]
generated: { by: "claude-code/claude-opus-5", at: "2026-10-12T00:00:00Z" }
---

# What this is for

Two use cases need the caller to *show* the agent something rather than describe it: a damaged ward asset and a damaged insured item ([/product/use-cases.md](/product/use-cases.md), 8 and 9). Both are the same mechanism. The caller turns on a camera, the agent looks when it needs to, says what it can actually see, and the call ends with a case a human can act on.

The hard part is not seeing. It is **not over-claiming**. A caller who says "there is a big crack" and an agent that agrees because agreeing is easy produces a case that falls apart at the first review, and in a healthcare product that is the failure that matters. So the observation carries a confidence it is allowed to withhold, and the agent is required to ask for a better look instead of guessing ([/product/healthcare-compliance.md](/product/healthcare-compliance.md)).

How a frame reaches the server: [/api/voice-protocol.md](/api/voice-protocol.md) and [ADR-0009](/decisions/adr-0009-video-channel.md). Where the bytes live: [/architecture/media-storage.md](/architecture/media-storage.md). The work belongs to the `evidence` module ([/architecture/modular-structure.md](/architecture/modular-structure.md)).

# Flow

```
caller enables camera ──▶ camera stays in the browser; nothing is sent
                                                      │
agent decides to look ──▶ look_at_camera ──▶ voice module asks for one frame
                                                      │ one JPEG, base64, on the call socket
                                                      ▼
                                              evidence module
                                                      │  1. store the frame
                                                      │  2. describe it: gateway "vision" role
                                                      │  3. pin it: media + observation + caller's words
                                                      ▼
                                      confidence: confirmed | unclear | not_confirmed
                                                      │
                        confirmed ──▶ case opened or updated ──▶ narrative, missing items
                        unclear / not_confirmed ──▶ agent asks for a closer or different look
                        safety_flag ──▶ immediate hand-off, whatever the case state
                                                      │
                                      routing decision ──▶ ticket in the business system
```

# Looking is an act, not a stream

The agent sees a frame **only when it calls `look_at_camera`**, a built-in tool alongside `search_knowledge`, `escalate_to_human` and `end_call` ([/architecture/agent-runtime.md](/architecture/agent-runtime.md)). Nothing streams to a model, and nothing streams to the server either.

This is a deliberate constraint, for four reasons that all point the same way:

* **Cost and latency.** A described frame is one vision call. A stream is a vision call per frame, and the caller is waiting.
* **Grounding.** An observation is anchored to a moment and to what the caller had just said. "The frame I looked at when you said that" is reviewable; "the model's impression of the last thirty seconds" is not.
* **Consent.** The caller can see when the agent looked, because the agent says so and the evidence strip gains an entry ([/ui/visual-case.md](/ui/visual-case.md)). Between looks the camera feed does not leave their machine.
* **The turn loop is unchanged.** A tool call is what the runtime already does, so turn detection, interruption, cost accounting and the fake-LLM test path all keep working.

The camera is **off until the caller turns it on**. The agent MAY ask; it MUST NOT be able to enable the camera itself, and neither the API nor the protocol offers a way to do so. The browser reports the camera's state; the server never requests a frame while that state is off.

A look that cannot produce a frame returns a **declined** result — camera off, the browser did not answer within 2 s, capture failed, or the per-call cap is spent ([/architecture/media-storage.md](/architecture/media-storage.md)). A declined look carries no observation, and the agent MUST then say what it needs rather than describe anything.

# The observation

One look produces one observation, as structured output from the `vision` role ([/architecture/llm-gateway.md](/architecture/llm-gateway.md)), validated against this shape. The prompt is [/prompts/vision-observation.md](/prompts/vision-observation.md).

| Field | Rules |
|---|---|
| `description` | What is visible, in plain language. One to three sentences. No diagnosis, no cause, no cost. |
| `items` | Zero or more named things the model can point at: `{label, detail}`. Empty is a valid answer. |
| `confidence` | `confirmed` · `unclear` · `not_confirmed`. See below. |
| `safety_flag` | `none` · `injury` · `unsafe_premises`. |
| `asked_for` | When confidence is not `confirmed`, what a better frame would need: closer, wider, more light, different angle. |

`confidence` is the load-bearing field:

* **`confirmed`** — what the caller described is visible in the frame.
* **`unclear`** — something is there but the frame cannot settle it. The frame is pinned and the agent asks for the look named in `asked_for`.
* **`not_confirmed`** — the frame does not show what was described. The model says what it *does* see. The frame is still pinned, labelled `not_confirmed`, and the case does not inherit the caller's characterisation.

`not_confirmed` MUST NOT be spoken as an accusation. The agent reports what it sees and asks for another look. A caller may well be right about a thing the camera has not yet caught.

# Evidence

Every look that produced a frame is pinned, including the ones that confirmed nothing — a withheld confidence is a finding, and discarding it would leave a reviewer unable to tell a careful agent from a lucky one. A declined look stores no evidence entry, because there is nothing to review.

An evidence entry holds the stored frame, the observation, the caller's own words from the turn that prompted the look, and its sequence in the call. Entries are append-only for the life of the call. The frame itself is subject to retention ([ADR-0010](/decisions/adr-0010-media-retention.md)); the observation text is not, so a case stays readable after its images expire.

# The case

A case opens on the **first `confirmed` observation**, or earlier if the caller states the intent outright ("I want to report a damaged bed"). One case per call, at most.

| Field | Rules |
|---|---|
| `kind` | `facility_fault` · `claim`. Decides which business-system tool files it and which skill guides the call. |
| `narrative` | Drafted from the evidence and the transcript ([/prompts/visual-case-draft.md](/prompts/visual-case-draft.md)), never from the caller's words alone. |
| `missing` | What the case still needs before a human can decide: a document, a policy number, a better frame, a location. |
| `routing` | `needs_docs` · `ready_for_review` · `siu_review` · `escalate`, with a one-line reason. |
| `ticket_ref` | The id the simulated business system returned, or empty. |

**The case is product state; the ticket is a business-system record.** The case lives here. The ticket id comes back from an ordinary data-driven tool against [/api/mock-healthcare-api.md](/api/mock-healthcare-api.md), the same way every other business write in this product happens. If that call fails, the case stays open with `ticket_ref` empty and the agent says the report is recorded but not yet filed — it MUST NOT invent a reference.

`siu_review` exists because visual claim intake is where fraud signals appear. It is a routing destination, not an accusation, and the agent never says the word to the caller; it hands off to the Special Investigations contact that already exists in the internal directory.

# Safety overrides everything

A `safety_flag` of `injury` or `unsafe_premises` triggers an immediate hand-off with category `safety` ([/architecture/escalation.md](/architecture/escalation.md)), whatever state the case is in. A half-built case is handed over as-is; the packet carries the evidence pinned so far. Waiting to finish a form while someone describes an injury is the wrong behaviour, and this rule exists to make that non-negotiable.

# A video call is a voice call that can see

`channel: "video"` is a voice call with a camera available. Nothing requires the camera: if the caller never enables it, the call behaves exactly as `channel: "voice"` — same brain, same tools, same ending rules. The agent offers reference images instead when it would have asked to look ([/architecture/imagery.md](/architecture/imagery.md)).

This matters for the demo and for degradation. No path through this spec is reachable only with a working camera.

# Acceptance

- **VI-01** — Given a published agent, when `POST /api/calls` is called with `channel: "video"`, then a call is created with channel `video`; and given no vision-capable model ref resolves, then the call is created as `voice` and the response carries `video_unavailable` with a reason.
- **VI-02** — Given a video call, when it starts, then the camera is off, and there is no API, protocol message or tool by which the agent can enable it; the caller enabling it is the only way a frame ever arrives.
- **VI-03** — Given a video call with the camera on, when the agent does not call `look_at_camera`, then no frame is requested, no frame leaves the browser, and no image is sent to any model.
- **VI-04** — Given a video call with the camera off, when the agent calls `look_at_camera`, then no frame is requested, the result is a declined status with no observation, and the agent's next turn asks the caller to turn the camera on rather than describing anything.
- **VI-05** — Given a frame, when `look_at_camera` runs, then exactly one observation is produced with `description`, `items`, `confidence` and `safety_flag`, validated against the schema, and a response that fails validation is retried once before the tool reports failure.
- **VI-06** — Given the caller describes damage the frame does not show, when the agent looks, then `confidence` is `not_confirmed`, `asked_for` names the better look required, the spoken reply states what is visible instead, and the case does not record the caller's characterisation as fact.
- **VI-07** — Given two looks in one call, when the evidence is read, then both are pinned in order with their observation, their confidence and the caller's words from the prompting turn, including the look that returned `not_confirmed`; and a declined look pins nothing.
- **VI-08** — Given a call with no case, when the first `confirmed` observation is pinned or the caller states the reporting intent, then exactly one case is opened; and when a second trigger occurs in the same call, then no second case is created.
- **VI-09** — Given a case with evidence, when the narrative is drafted, then it states only what the observations support, and `missing` lists each item the case still needs.
- **VI-10** — Given a case, when it is closed, then `routing` is one of `needs_docs`, `ready_for_review`, `siu_review` or `escalate` with a reason, and the caller is never told that the routing is `siu_review`.
- **VI-11** — Given any observation with `safety_flag` of `injury` or `unsafe_premises`, when it is pinned, then a hand-off with category `safety` is opened in the same turn, the packet carries the evidence pinned so far, and it happens whether or not a case exists.
- **VI-12** — Given a case ready to file, when the business-system tool succeeds, then `ticket_ref` holds the returned id; and when it fails, then the case stays open with `ticket_ref` empty and the spoken reply says the report is recorded but not filed.
- **VI-13** — Given a case and its media belonging to one tenant, when another tenant requests them by id, then the result is indistinguishable from not found.
- **VI-14** — Given a video call where the caller never enables the camera, when the call runs to its end, then it behaves as a voice call throughout and completes with a normal end reason.
- **VI-15** — Given the agent asks for a frame and the browser does not answer within 2 s, when the tool returns, then the result is a declined status, the call continues, and a frame arriving after the timeout is discarded rather than stored or described.
