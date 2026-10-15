---
type: UI Spec
title: Visual evidence and cases
description: "The camera control and evidence strip in a video test call, the case card, the sample-image path when there is no webcam, and how evidence reads back on Calls and in the console."
status: draft
tags: [ui, video, evidence, cases]
generated: { by: "claude-code/claude-opus-5", at: "2026-10-12T00:00:00Z" }
---

# Starting a video call (`/test-call/`)

The call card's channel switch becomes **Talk | Video | Type** ([/ui/test-call.md](/ui/test-call.md)). **Video** starts a call with `channel: "video"`, then joins the LiveKit room the response names using `livekit-client` ([/api/media-protocol.md](/api/media-protocol.md)). Everything else about the page is unchanged, because a video call is a voice call that can see ([/architecture/visual-intake.md](/architecture/visual-intake.md)); the microphone is published on connect and the agent's audio track is attached for playback.

* The switch offers **Video** only for agents whose use cases advertise the channel. For other agents it is present but disabled, with the hint "This agent does not take visual reports".
* If the call response carries `video_unavailable`, the call runs as Talk and a notice names the specific cause — which `LIVEKIT_*` setting is unset, that the `livekit` package is not installed, or that no vision model has a usable key — and says the call is running as voice. The tester is not left guessing why the camera control is missing.

# The call layout

A video call is laid out like one ([/architecture/avatar.md](/architecture/avatar.md)).

* **The agent tile** is the main area: the agent's video when the call has an avatar, otherwise a **placeholder** with the persona's name and a speaking indicator that moves while the agent talks. Either way it is labelled with the persona's name and **AI agent**, always visible, so the face is never mistaken for a person (UI-46, compliance rule 13).
* **The caller's own camera** is a small **self-view** in a corner of the tile, never a full-width strip above the transcript.
* When the call has no avatar because none is configured, the placeholder carries a quiet line, "No avatar is configured", so a tester is not left wondering. When the avatar failed mid-call the tile falls back to the placeholder with "Avatar unavailable — the agent can still be heard" (UI-47). The speaking indicator works in both cases (UI-48).
* The transcript, evidence strip and case card are unchanged.

# The camera control

A **Camera** button sits beside the mic button, **off when the call starts**. Nothing in the page lets the agent turn it on — only this button does.

* **Off**: the label reads "Camera off". No video is captured and nothing is sent.
* **On**: the camera track is published to the room and a local **self-view** appears in the corner of the agent tile.
* While the camera is on, a **"Your camera is live. The agent looks only when it asks."** hint sits under the tile. It is the honest wording for this transport: video is flowing while the camera is on ([ADR-0009](/decisions/adr-0009-video-channel.md)), and what the agent is shown is only the frames a look asked for.
* Turning the camera off mid-call is immediate and needs no confirmation. Looks already pinned stay pinned.
* Turning it off unpublishes the track. When permission is refused or no camera exists, the button is replaced by **Use a sample image** (below) and the transcript shows "No camera available — you can send a sample image instead."

Each time the agent looks, a **shutter flash on the preview and a "The agent looked" system notice** appear in the transcript. The caller always knows a frame was taken, which is the consent property the architecture requires.

# Evidence strip

A card in the right column, **Evidence**, appears with the first look and lists entries newest last:

| Part | Shows |
|---|---|
| Thumbnail | The stored frame, from the authorised media endpoint; a placeholder with "Image expired" once retention has removed it ([/architecture/media-storage.md](/architecture/media-storage.md)) |
| Confidence chip | **Confirmed** (success tone), **Unclear** (warning tone), **Not confirmed** (neutral tone, never the danger tone) |
| `Sample` tag | On entries whose source is a sample image ([/architecture/imagery.md](/architecture/imagery.md)) |
| Description | The observation text |
| Caller's words | The quoted turn that prompted the look, in the muted caption style |
| Asked for | When present: "Agent asked for: a closer look at the hinge" |

**Not confirmed** is styled as information, not as an error. It is a correct and expected outcome, and a red chip would teach the opposite.

A declined look adds no entry; it shows only as a system notice in the transcript ("Camera is off — the agent asked the caller to turn it on").

# Case card

Below Evidence, a **Case** card appears when a case opens:

* **Kind** badge — *Facility fault* or *Claim*.
* **Narrative** — the drafted text.
* **Still needed** — the `missing` list as a checklist, or "Nothing outstanding".
* **Routing** — the destination with its one-line reason. `siu_review` renders as **Specialist review** with its reason; the words "special investigations" and "fraud" appear nowhere in the caller-facing transcript, and the routing reason is shown only in this card and on Calls, never read out.
* **Ticket** — the reference, or "Recorded, not yet filed" when the business system did not answer.

# Sample images

**Use a sample image** opens a picker of the seeded samples, each with its label ("Bent bed side-rail", "Cracked footplate", "Water-stained ceiling tile", "Dented car door"). Choosing one makes it the frame the next look captures, exactly once.

The picker is headed "Synthetic demo images" and every entry it produces is tagged **Sample** in the evidence strip and in the case. Nothing in this path can produce an untagged entry.

# Reading it back

* **Calls** ([/ui/calls.md](/ui/calls.md)) — call detail shows the same Evidence strip and Case card, read-only, under the transcript. The explorer's channel filter gains **Video**.
* **Agent console** ([/ui/agent-console.md](/ui/agent-console.md)) — a packet from a call with evidence shows the thumbnails and confidences above the summary, so the human sees what the agent saw before reading what it concluded. A `safety` hand-off from a visual call shows them first.

# Acceptance

- **UI-38** — Given a video-capable agent, when **Video** is selected and the call starts, then the camera is off, the Camera button reads "Camera off", and no preview is shown; and given an agent whose use cases do not advertise video, the Video option is disabled with its hint.
- **UI-39** — Given a running video call, when the camera is turned on, then the track is published, a self-view of it appears in the corner of the agent tile with the "Your camera is live" hint, and turning the camera off again unpublishes it and removes the self-view.
- **UI-40** — Given the camera is on, when the agent looks, then the preview flashes, a "The agent looked" notice appears in the transcript, and an Evidence entry appears with its thumbnail, confidence chip, description and the quoted caller turn.
- **UI-41** — Given an observation with confidence `not_confirmed`, then its chip reads "Not confirmed" in the neutral tone (not the danger tone), its description is shown, and the "Agent asked for" line names the better look.
- **UI-42** — Given a case with `routing: siu_review`, then the Case card shows "Specialist review" with its reason, and neither the transcript nor any caller-facing text contains "fraud" or "special investigations".
- **UI-43** — Given a browser with no camera, then the Camera button is replaced by "Use a sample image", and an image chosen from the picker produces an Evidence entry tagged **Sample**.
- **UI-44** — Given a call whose media has passed the retention window, when its detail is opened on Calls, then each thumbnail is a placeholder reading "Image expired" while the description, confidence and caller's words are still shown.
- **UI-45** — Given `video_unavailable` in the call response, then the call runs as Talk, the notice names the reason, and no camera control is offered.
- **UI-46** — Given a video call whose response has `media.avatar` true, when the agent's video track arrives, then it fills the main tile, which is labelled with the persona's name and "AI agent", and the caller's camera, when on, is a small self-view in a corner and not a full-width strip.
- **UI-47** — Given a video call with `media.avatar` false, or an avatar that fails mid-call, then the main tile shows the placeholder with the persona's name and "AI agent", the line "No avatar is configured" or "Avatar unavailable — the agent can still be heard", and the call carries on with the agent audible.
- **UI-48** — Given the agent is speaking, when the call has no avatar track, then the placeholder shows a speaking indicator while it speaks and not while it is silent.
- **UI-49** — Given a video call whose `media.engine` is `gemini_live` and `media.avatar` true, when `avatar_video` messages arrive, then the page plays them in the main tile through a media source so the face and its voice are one stream, shows the persona's name and **AI agent** (UI-46), and drops everything buffered on `interrupt`.
- **UI-50** — Given a Live-engine call whose avatar stream cannot be played, or a `notice` with `avatar: false`, then the page sends `{"type":"avatar","enabled":false}` when it cannot play, shows the placeholder tile with the reason, the agent is still heard through `audio` messages, and the call continues.
- **UI-51** — Given a Live-engine call, when a `frame_request` arrives and the camera is on, then the page captures exactly one still and answers with it, flashes the shutter and adds the "The agent looked" notice; and given the camera is off, then it answers `declined`; and given no request, no frame is ever sent.
