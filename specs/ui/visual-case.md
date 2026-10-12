---
type: UI Spec
title: Visual evidence and cases
description: "The camera control and evidence strip in a video test call, the case card, the sample-image path when there is no webcam, and how evidence reads back on Calls and in the console."
status: draft
tags: [ui, video, evidence, cases]
generated: { by: "claude-code/claude-opus-5", at: "2026-10-12T00:00:00Z" }
---

# Starting a video call (`/test-call/`)

The call card's channel switch becomes **Talk | Video | Type** ([/ui/test-call.md](/ui/test-call.md)). **Video** starts a call with `channel: "video"`; everything else about the page is unchanged, because a video call is a voice call that can see ([/architecture/visual-intake.md](/architecture/visual-intake.md)).

* The switch offers **Video** only for agents whose use cases advertise the channel. For other agents it is present but disabled, with the hint "This agent does not take visual reports".
* If the call response carries `video_unavailable`, the call runs as Talk and a notice reads "Video is unavailable: no vision model is configured. The call is running as voice." The tester is not left guessing why the camera control is missing.

# The camera control

A **Camera** button sits beside the mic button, **off when the call starts**. Nothing in the page lets the agent turn it on — only this button does.

* **Off**: the label reads "Camera off". No video is captured and nothing is sent.
* **On**: the browser preview appears above the input area at a size that does not push the transcript off screen (a 160 px-tall strip on wide viewports, collapsible on narrow ones). The preview is local; it is not uploaded.
* While the camera is on, a **"The agent can ask to look"** hint sits under the preview. It is the honest wording: the agent cannot see the preview, only the frames it asks for.
* Turning the camera off mid-call is immediate and needs no confirmation. Looks already pinned stay pinned.
* When permission is refused or no camera exists, the button is replaced by **Use a sample image** (below) and the transcript shows "No camera available — you can send a sample image instead."

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
- **UI-39** — Given a running video call, when the camera is turned on, then a local preview appears with the "The agent can ask to look" hint, and nothing is uploaded until the agent looks.
- **UI-40** — Given the camera is on, when the agent looks, then the preview flashes, a "The agent looked" notice appears in the transcript, and an Evidence entry appears with its thumbnail, confidence chip, description and the quoted caller turn.
- **UI-41** — Given an observation with confidence `not_confirmed`, then its chip reads "Not confirmed" in the neutral tone (not the danger tone), its description is shown, and the "Agent asked for" line names the better look.
- **UI-42** — Given a case with `routing: siu_review`, then the Case card shows "Specialist review" with its reason, and neither the transcript nor any caller-facing text contains "fraud" or "special investigations".
- **UI-43** — Given a browser with no camera, then the Camera button is replaced by "Use a sample image", and an image chosen from the picker produces an Evidence entry tagged **Sample**.
- **UI-44** — Given a call whose media has passed the retention window, when its detail is opened on Calls, then each thumbnail is a placeholder reading "Image expired" while the description, confidence and caller's words are still shown.
- **UI-45** — Given `video_unavailable` in the call response, then the call runs as Talk, the notice names the reason, and no camera control is offered.
